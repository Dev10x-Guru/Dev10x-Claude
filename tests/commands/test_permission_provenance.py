"""Tests for `dev10x permission provenance` and `seed-worktree` (GH-602)."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from dev10x.commands.permission import provenance as provenance_cmd
from dev10x.commands.permission import seed_worktree as seed_worktree_cmd
from dev10x.domain.common.result import err, ok


@pytest.fixture(autouse=True)
def _config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from dev10x.skills.permission import update_paths as paths_mod

    monkeypatch.setattr(paths_mod, "find_config", lambda: ok(tmp_path / "config.yaml"))
    monkeypatch.setattr(paths_mod, "load_config", lambda _path: {"base_permissions": []})


def test_provenance_prints_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    from dev10x.skills.permission import provenance as mod

    monkeypatch.setattr(
        mod,
        "build_provenance",
        lambda **_kw: ok(
            {
                "path": "/p/.claude/settings.local.json",
                "rules": [{"rule": "Bash(ls:*)", "kind": "allow", "provenance": "default"}],
                "counts": {"default": 1, "user": 0, "project": 0},
            }
        ),
    )
    result = CliRunner().invoke(provenance_cmd, [])
    assert result.exit_code == 0
    assert "default: 1" in result.output
    assert "[default] allow: Bash(ls:*)" in result.output


def test_provenance_error_exits_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    from dev10x.skills.permission import provenance as mod

    monkeypatch.setattr(mod, "build_provenance", lambda **_kw: err("settings file not found"))
    result = CliRunner().invoke(provenance_cmd, ["--path", "/nope.json"])
    assert result.exit_code == 1
    assert "not found" in result.output


def test_seed_worktree_reports_count(monkeypatch: pytest.MonkeyPatch) -> None:
    from dev10x.skills.permission import update_paths as paths_mod

    monkeypatch.setattr(
        paths_mod,
        "seed_worktree",
        lambda **_kw: ok({"path": "/wt/.claude/settings.local.json", "added": 5}),
    )
    result = CliRunner().invoke(seed_worktree_cmd, ["/wt"])
    assert result.exit_code == 0
    assert "Seeded 5 rule(s)" in result.output


def test_seed_worktree_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    from dev10x.skills.permission import update_paths as paths_mod

    monkeypatch.setattr(
        paths_mod,
        "seed_worktree",
        lambda **_kw: ok({"path": "/wt/.claude/settings.local.json", "added": 0}),
    )
    result = CliRunner().invoke(seed_worktree_cmd, ["/wt", "--dry-run"])
    assert result.exit_code == 0
    assert "Would seed 0 rule(s)" in result.output


def test_seed_worktree_error_exits_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    from dev10x.skills.permission import update_paths as paths_mod

    monkeypatch.setattr(paths_mod, "seed_worktree", lambda **_kw: err("cannot create"))
    result = CliRunner().invoke(seed_worktree_cmd, ["/wt"])
    assert result.exit_code == 1
    assert "cannot create" in result.output
