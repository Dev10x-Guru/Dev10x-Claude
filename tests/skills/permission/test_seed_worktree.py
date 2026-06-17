"""Tests for seed-at-worktree-creation (GH-602)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.domain.common.result import ErrorResult, SuccessResult
from dev10x.skills.permission import enumerate_mcp
from dev10x.skills.permission import update_paths as mod


@pytest.fixture
def config() -> dict:
    return {
        "base_permissions": ["Bash(ls:*)", "Skill(Dev10x:foo)"],
        "base_denies": ["Bash(sudo:*)"],
    }


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "_load_global_allow_rules", lambda: (set(), []))
    monkeypatch.setattr(enumerate_mcp, "discover_mcp_tools", lambda **_kw: {})


def _allow(worktree: Path) -> list[str]:
    data = json.loads((worktree / ".claude" / "settings.local.json").read_text())
    return data["permissions"]["allow"]


def test_seeds_fresh_worktree(tmp_path: Path, config: dict):
    result = mod.seed_worktree(worktree_root=tmp_path, config=config)
    assert isinstance(result, SuccessResult)
    assert result.value["created_fresh"] is True
    assert result.value["added"] == 3
    settings = tmp_path / ".claude" / "settings.local.json"
    data = json.loads(settings.read_text())
    assert "Bash(ls:*)" in data["permissions"]["allow"]
    assert "Bash(sudo:*)" in data["permissions"]["deny"]


def test_dry_run_writes_nothing(tmp_path: Path, config: dict):
    result = mod.seed_worktree(worktree_root=tmp_path, config=config, dry_run=True)
    assert isinstance(result, SuccessResult)
    assert result.value["would_create"] is True
    assert not (tmp_path / ".claude" / "settings.local.json").exists()


def test_idempotent(tmp_path: Path, config: dict):
    mod.seed_worktree(worktree_root=tmp_path, config=config)
    second = mod.seed_worktree(worktree_root=tmp_path, config=config)
    assert second.value["added"] == 0
    assert second.value["created_fresh"] is False


def test_dedupes_against_global(tmp_path: Path, config: dict, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(mod, "_load_global_allow_rules", lambda: ({"Bash(ls:*)"}, []))
    mod.seed_worktree(worktree_root=tmp_path, config=config)
    allow = _allow(tmp_path)
    assert "Bash(ls:*)" not in allow  # already global — skipped
    assert "Skill(Dev10x:foo)" in allow


def test_create_error_is_reported(tmp_path: Path, config: dict):
    blocker = tmp_path / "afile"
    blocker.write_text("x")  # a file where the worktree dir should be
    result = mod.seed_worktree(worktree_root=blocker, config=config)
    assert isinstance(result, ErrorResult)
    assert "cannot create" in result.error
