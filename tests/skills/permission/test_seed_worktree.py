"""Tests for seed-at-worktree-creation (GH-602, GH-1405).

Since GH-1405 the counts below include the two safety keys (GH-1320):
``seed_worktree`` delegates the whole write sequence to ``ensure_base``
rather than calling two of its three tier writers by hand, so a fresh
worktree now receives exactly what a checkout receives.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.domain.common.result import ErrorResult, SuccessResult
from dev10x.skills.permission import catalog_write as mod
from dev10x.skills.permission import enumerate_mcp


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
    assert result.value["added"] == 5  # 2 allow + 1 deny + 2 safety keys
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


def test_dedupes_against_global_when_opted_in(
    tmp_path: Path, config: dict, monkeypatch: pytest.MonkeyPatch
):
    """Opt-in only since GH-1136 — see test_catalog_gap.py for the default."""
    monkeypatch.setattr(mod, "_load_global_allow_rules", lambda: ({"Bash(ls:*)"}, []))
    mod.seed_worktree(worktree_root=tmp_path, config=config, dedupe_global=True)
    allow = _allow(tmp_path)
    assert "Bash(ls:*)" not in allow  # already global — skipped
    assert "Skill(Dev10x:foo)" in allow


def test_create_error_is_reported(tmp_path: Path, config: dict):
    blocker = tmp_path / "afile"
    blocker.write_text("x")  # a file where the worktree dir should be
    result = mod.seed_worktree(worktree_root=blocker, config=config)
    assert isinstance(result, ErrorResult)
    assert "cannot create" in result.error


def test_seeds_tilde_rule_with_home_twin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Routing through render_permissions now emits the GH-47 /home/<user>/
    twin alongside every ~/ rule (the one intended diff vs the flat shim)."""
    monkeypatch.setattr(
        "dev10x.skills.permission.catalog_write.Path.home",
        lambda: Path("/home/tester"),
    )
    config = {"base_permissions": ["Read(~/.claude/memory/**)"], "base_denies": []}
    result = mod.seed_worktree(worktree_root=tmp_path, config=config)
    allow = _allow(tmp_path)
    assert "Read(~/.claude/memory/**)" in allow
    assert "Read(/home/tester/.claude/memory/**)" in allow
    assert result.value["added"] == 4  # 2 allow + 2 safety keys


def _settings(worktree: Path) -> dict:
    return json.loads((worktree / ".claude" / "settings.local.json").read_text())


class TestConvergedOnEnsureBase:
    """GH-1405: a fresh worktree gets what a checkout gets, not a subset.

    Each test below is one omission the hand-rolled write sequence had.
    They are separate tests rather than one because they failed
    independently — a worktree could have asks and no safety keys — and a
    single combined assertion would not say which convergence regressed.
    """

    def test_seeds_base_asks(self, tmp_path: Path):
        config = {
            "base_permissions": [],
            "base_denies": [],
            "base_asks": ["Bash(gh api --method DELETE:*)"],
        }
        mod.seed_worktree(worktree_root=tmp_path, config=config)
        assert "Bash(gh api --method DELETE:*)" in _settings(tmp_path)["permissions"]["ask"]

    def test_seeds_safety_keys(self, tmp_path: Path, config: dict):
        mod.seed_worktree(worktree_root=tmp_path, config=config)
        data = _settings(tmp_path)
        assert data["disableAutoMode"] == "disable"
        assert data["disableBypassPermissionsMode"] == "disable"

    def test_seeds_ide_denies_without_a_pinned_ide(self, tmp_path: Path):
        # GH-1261: the shell-equivalent denies are unconditional, so they
        # must reach a worktree that pinned no IDE at all.
        config = {
            "base_permissions": [],
            "base_denies": ["mcp__pycharm__execute_terminal_command"],
        }
        mod.seed_worktree(worktree_root=tmp_path, config=config)
        assert (
            "mcp__pycharm__execute_terminal_command" in _settings(tmp_path)["permissions"]["deny"]
        )

    def test_residual_gap_is_an_error_not_a_silent_success(
        self, tmp_path: Path, config: dict, monkeypatch: pytest.MonkeyPatch
    ):
        # GH-1136's lesson applied to the worktree path: reporting success
        # while the file still lacks catalog rules is the defect itself.
        monkeypatch.setattr(
            mod,
            "_residual_gap_errors",
            lambda **_kw: ["ERROR: still missing 7 allow / 0 deny / 0 ask catalog rules."],
        )
        result = mod.seed_worktree(worktree_root=tmp_path, config=config)
        assert isinstance(result, ErrorResult)
        assert "residual catalog gap" in result.error
