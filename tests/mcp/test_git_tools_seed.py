"""Tests for worktree-creation seeding at the MCP boundary (GH-602)."""

from __future__ import annotations

import pytest

from dev10x.domain.common.result import err, ok
from dev10x.mcp.git_tools import _seed_worktree_defaults


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch):
    """Wire find_config/load_config to succeed; caller sets seed_worktree."""
    from dev10x.skills.permission import update_paths as paths_mod

    monkeypatch.setattr(paths_mod, "find_config", lambda: ok("/cfg.yaml"))
    monkeypatch.setattr(paths_mod, "load_config", lambda _path: {"base_permissions": []})
    return paths_mod


def test_skips_on_error_result(wired):
    result = {"error": "boom"}
    _seed_worktree_defaults(result)
    assert "seeded_permissions" not in result


def test_skips_without_worktree_path(wired):
    result = {"created": True}
    _seed_worktree_defaults(result)
    assert "seeded_permissions" not in result


def test_records_seeded_count(wired, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(wired, "seed_worktree", lambda **_kw: ok({"added": 9}))
    result = {"worktree_path": "/wt", "created": True}
    _seed_worktree_defaults(result)
    assert result["seeded_permissions"] == 9


def test_records_seed_error(wired, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(wired, "seed_worktree", lambda **_kw: err("cannot create"))
    result = {"worktree_path": "/wt"}
    _seed_worktree_defaults(result)
    assert result["seed_error"] == "cannot create"


def test_skips_when_config_missing(wired, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(wired, "find_config", lambda: err("no config"))
    result = {"worktree_path": "/wt"}
    _seed_worktree_defaults(result)
    assert "seeded_permissions" not in result
    assert "seed_error" not in result


def test_oserror_is_recorded(wired, monkeypatch: pytest.MonkeyPatch):
    def _boom(**_kw):
        raise OSError("disk full")

    monkeypatch.setattr(wired, "seed_worktree", _boom)
    result = {"worktree_path": "/wt"}
    _seed_worktree_defaults(result)
    assert "disk full" in result["seed_error"]
