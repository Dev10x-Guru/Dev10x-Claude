"""Tests for `dev10x permission merge-worktree` (GH-1790)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner
from dev10x.domain.common.result import err, ok
from dev10x.skills.permission.declined_catalog import declined_path, load_declined_rules

from dev10x.commands.permission import merge_worktree
from dev10x.skills.permission import declined_catalog
from dev10x.skills.permission import merge_worktree_permissions as mod

MAIN = Path("/work/proj")
WORKTREE = Path("/work/proj/.worktrees/wt-1")

type MergeStub = Callable[..., tuple[int, list[str]]]


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch) -> Callable[[MergeStub], None]:
    """Point the command at one project and a stubbed merge."""
    monkeypatch.setattr(mod, "find_config", lambda: ok(Path("/cfg.yaml")))
    monkeypatch.setattr(mod, "load_config", lambda _path: {"roots": ["/work"]})
    monkeypatch.setattr(mod, "find_worktree_groups", lambda _roots: {MAIN: [WORKTREE]})

    def _use(merge: MergeStub) -> None:
        monkeypatch.setattr(mod, "merge_permissions", merge)

    return _use


@pytest.fixture
def merged(cli_env: Callable[[MergeStub], None]) -> dict[str, object]:
    seen: dict[str, object] = {}

    def _merge(**kwargs: object) -> tuple[int, list[str]]:
        seen.update(kwargs)
        return 1, ["  target: /work/proj/.claude/settings.local.json", "    + Bash(git log:*)"]

    cli_env(_merge)
    return seen


def test_exclude_is_recorded_and_forwarded(merged: dict[str, object]) -> None:
    result = CliRunner().invoke(merge_worktree, ["--exclude", "Bash(psql:*)"])

    assert result.exit_code == 0
    assert "Declined: Bash(psql:*)" in result.output
    assert load_declined_rules() == frozenset({"Bash(psql:*)"})
    assert merged["declined"] == frozenset({"Bash(psql:*)"})
    assert "Merged 1 permissions into 1 projects." in result.output


def test_dry_run_exclude_is_reported_not_recorded(merged: dict[str, object]) -> None:
    result = CliRunner().invoke(merge_worktree, ["--dry-run", "--exclude", "Bash(curl:*)"])

    assert result.exit_code == 0
    assert "Would decline: Bash(curl:*) (not recorded under --dry-run)" in result.output
    assert load_declined_rules() == frozenset()
    assert merged["declined"] == frozenset({"Bash(curl:*)"})
    assert "Would merge 1 permissions" in result.output


def test_held_only_project_still_prints_its_report(
    cli_env: Callable[[MergeStub], None],
) -> None:
    cli_env(lambda **_kw: (0, ["  target: x", "  held back 1 rule(s) — not copied:"]))

    result = CliRunner().invoke(merge_worktree, [])

    assert result.exit_code == 0
    assert "held back 1 rule(s)" in result.output
    assert "All projects up to date." in result.output


def test_decline_failure_exits_non_zero(
    merged: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(declined_catalog, "decline_rules", lambda **_kw: err("locked"))

    result = CliRunner().invoke(merge_worktree, ["--exclude", "Bash(psql:*)"])

    assert result.exit_code == 1
    assert "ERROR: locked" in result.output
    assert merged == {}


def test_broken_declined_file_stops_the_merge(merged: dict[str, object]) -> None:
    declined_path().parent.mkdir(parents=True, exist_ok=True)
    declined_path().write_text("{not: [yaml")

    result = CliRunner().invoke(merge_worktree, [])

    assert result.exit_code == 1
    assert "declined rules cannot be honoured" in result.output
    assert merged == {}
