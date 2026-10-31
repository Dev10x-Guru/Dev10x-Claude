"""Tests for `dev10x permission sync-worktrees` (GH-1673)."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner
from dev10x.domain.common.result import ok
from dev10x.permission.service import PermissionContext

from dev10x.commands import permission as commands
from dev10x.commands.permission import sync_worktrees
from dev10x.skills.permission import merge_worktree_permissions as mod

MAIN = Path("/work/proj")
WORKTREE = Path("/work/.herdr/worktrees/proj/wt-1")


@pytest.fixture(autouse=True)
def _context(monkeypatch: pytest.MonkeyPatch) -> None:
    context = PermissionContext(
        config_path=Path("/cfg.yaml"),
        config={"roots": ["/work"]},
        settings_files=[],
    )
    monkeypatch.setattr(commands, "load_permission_context", lambda **_kw: ok(context))


def test_reports_rules_added_per_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def _sync(**kwargs: object) -> tuple[int, list[str]]:
        seen.update(kwargs)
        return 2, ["  target: /wt", "    + mcp__chrome-devtools__take_snapshot"]

    monkeypatch.setattr(mod, "find_repo_families", lambda *_a, **_kw: {MAIN: [WORKTREE]})
    monkeypatch.setattr(mod, "sync_main_to_worktrees", _sync)

    result = CliRunner().invoke(sync_worktrees, [])

    assert result.exit_code == 0
    assert "/work/proj -> 1 worktree(s)" in result.output
    assert "Added 2 rule(s) across 1 repo(s)." in result.output
    assert seen == {"main_project": MAIN, "worktree_dirs": [WORKTREE], "dry_run": False}


def test_dry_run_forwards_dry_run_and_says_would_add(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def _sync(**kwargs: object) -> tuple[int, list[str]]:
        seen.update(kwargs)
        return 0, []

    monkeypatch.setattr(mod, "find_repo_families", lambda *_a, **_kw: {MAIN: [WORKTREE]})
    monkeypatch.setattr(mod, "sync_main_to_worktrees", _sync)

    result = CliRunner().invoke(sync_worktrees, ["--dry-run"])

    assert result.exit_code == 0
    assert seen["dry_run"] is True
    assert "(dry run — no files will be modified)" in result.output
    assert "Would add 0 rule(s) across 1 repo(s)." in result.output


def test_nothing_to_sync_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "find_repo_families", lambda *_a, **_kw: {})

    result = CliRunner().invoke(sync_worktrees, [])

    assert result.exit_code == 0
    assert "No main checkout with seeded worktrees found" in result.output
