"""Catalog propagation into project files (GH-1136)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.skills.permission import enumerate_mcp
from dev10x.skills.permission import update_paths as mod
from dev10x.skills.permission.catalog_gap import compute_gap, format_gap_report, rule_family


@pytest.fixture
def config() -> dict:
    return {
        "base_permissions": ["Bash(ls:*)", "Skill(Dev10x:foo)"],
        "base_denies": ["Bash(sudo:*)"],
    }


@pytest.fixture
def settings_file(tmp_path: Path) -> Path:
    path = tmp_path / "settings.local.json"
    path.write_text("{}\n")
    return path


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(enumerate_mcp, "discover_mcp_tools", lambda **_kw: {})
    monkeypatch.setattr(mod, "_is_git_tracked", lambda _path: False)


def _allow(path: Path) -> list[str]:
    return json.loads(path.read_text())["permissions"]["allow"]


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        ("mcp__plugin_Dev10x_cli__pr_get", "mcp"),
        ("Skill(Dev10x:git-commit)", "skill"),
        ("Read(~/.claude/plugins/**)", "read"),
        ("Bash(git develop-log:*)", "git"),
        ("Bash(gh pr view:*)", "gh"),
        ("Bash(uvx dev10x permission:*)", "dev10x-cli"),
        ("Bash(rg:*)", "bash"),
        ("WebFetch(domain:example.com)", "other"),
    ],
)
def test_rule_family_classification(rule: str, expected: str):
    assert rule_family(rule) == expected


def test_gap_reports_missing_rules(settings_file: Path):
    gap = compute_gap(
        path=settings_file,
        base_permissions=["Bash(ls:*)", "Bash(rg:*)"],
        base_denies=["Bash(sudo:*)"],
    )
    assert gap.missing_allow == ["Bash(ls:*)", "Bash(rg:*)"]
    assert gap.missing_deny == ["Bash(sudo:*)"]
    assert gap.total_missing == 3
    assert not gap.is_empty


def test_gap_is_empty_when_file_carries_catalog(settings_file: Path):
    settings_file.write_text(
        json.dumps({"permissions": {"allow": ["Bash(ls:*)"], "deny": ["Bash(sudo:*)"]}})
    )
    gap = compute_gap(
        path=settings_file,
        base_permissions=["Bash(ls:*)"],
        base_denies=["Bash(sudo:*)"],
    )
    assert gap.is_empty


def test_unreadable_file_is_a_gap_not_a_pass(tmp_path: Path):
    gap = compute_gap(
        path=tmp_path / "absent.json",
        base_permissions=["Bash(ls:*)"],
        base_denies=[],
    )
    assert gap.unreadable is not None
    assert gap.missing_allow == ["Bash(ls:*)"]


def test_report_groups_counts_by_family(settings_file: Path):
    gap = compute_gap(
        path=settings_file,
        base_permissions=["Bash(git log:*)", "Bash(git show:*)", "Skill(Dev10x:foo)"],
        base_denies=[],
    )
    report = "\n".join(format_gap_report(gap))
    assert "allow/git: 2" in report
    assert "allow/skill: 1" in report
    assert "Bash(git log:*)" not in report  # counts only unless verbose


def test_report_lists_rules_when_verbose(settings_file: Path):
    gap = compute_gap(
        path=settings_file,
        base_permissions=["Bash(git log:*)"],
        base_denies=[],
    )
    report = "\n".join(format_gap_report(gap, verbose=True))
    assert "+ Bash(git log:*)" in report


def test_rule_in_global_still_written_to_project_file(
    settings_file: Path,
    config: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """The GH-1136 regression: global coverage is not project coverage."""
    monkeypatch.setattr(mod, "_load_global_allow_rules", lambda: ({"Bash(ls:*)"}, []))
    result = mod.ensure_base(
        config=config,
        settings_files=[settings_file],
        dry_run=False,
    )
    assert result["exit_code"] == 0
    assert "Bash(ls:*)" in _allow(settings_file)


def test_dedupe_global_opt_in_restores_old_behaviour(
    settings_file: Path,
    config: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(mod, "_load_global_allow_rules", lambda: ({"Bash(ls:*)"}, []))
    result = mod.ensure_base(
        config=config,
        settings_files=[settings_file],
        dry_run=False,
        dedupe_global=True,
    )
    allow = _allow(settings_file)
    assert "Bash(ls:*)" not in allow
    assert "Skill(Dev10x:foo)" in allow
    # The residual check measures what the run intended to write, so opting
    # into dedupe does not then fail on the rules it was told to skip.
    assert result["exit_code"] == 0
    # ...but catalog-gap, which never dedupes, still names the real gap.
    gap = mod.catalog_gap(config=config, settings_files=[settings_file])
    assert gap["exit_code"] == 1


def test_git_tracked_settings_json_is_skipped(
    tmp_path: Path,
    config: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    tracked = tmp_path / "settings.json"
    tracked.write_text("{}\n")
    monkeypatch.setattr(mod, "_load_global_allow_rules", lambda: (set(), []))
    monkeypatch.setattr(mod, "_is_git_tracked", lambda path: path.name == "settings.json")

    result = mod.ensure_base(config=config, settings_files=[tracked], dry_run=False)

    assert json.loads(tracked.read_text()) == {}
    assert any("SKIP (git-tracked)" in m for m in result["messages"])


def test_untracked_settings_json_is_written(
    tmp_path: Path,
    config: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    untracked = tmp_path / "settings.json"
    untracked.write_text("{}\n")
    monkeypatch.setattr(mod, "_load_global_allow_rules", lambda: (set(), []))

    mod.ensure_base(config=config, settings_files=[untracked], dry_run=False)

    assert "Bash(ls:*)" in _allow(untracked)


def test_per_file_counts_are_reported(
    settings_file: Path,
    config: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(mod, "_load_global_allow_rules", lambda: (set(), []))
    result = mod.ensure_base(config=config, settings_files=[settings_file], dry_run=False)
    report = "\n".join(result["messages"])
    assert "Per-file added counts:" in report
    assert str(settings_file) in report


def test_dry_run_does_not_report_a_residual_gap(
    settings_file: Path,
    config: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """A dry run wrote nothing by design — it must not fail on that."""
    monkeypatch.setattr(mod, "_load_global_allow_rules", lambda: (set(), []))
    result = mod.ensure_base(config=config, settings_files=[settings_file], dry_run=True)
    assert result["exit_code"] == 0
    assert result["errors"] == []


def test_catalog_gap_reports_and_exits_non_zero(settings_file: Path, config: dict):
    result = mod.catalog_gap(config=config, settings_files=[settings_file])
    assert result["exit_code"] == 1
    assert "missing allow" in "\n".join(result["messages"])


def test_catalog_gap_is_clean_after_ensure_base(
    settings_file: Path,
    config: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(mod, "_load_global_allow_rules", lambda: (set(), []))
    mod.ensure_base(config=config, settings_files=[settings_file], dry_run=False)
    result = mod.catalog_gap(config=config, settings_files=[settings_file])
    assert result["exit_code"] == 0
    assert "0 missing allow / 0 missing deny" in "\n".join(result["messages"])


def test_catalog_gap_writes_nothing(settings_file: Path, config: dict):
    before = settings_file.read_text()
    mod.catalog_gap(config=config, settings_files=[settings_file])
    assert settings_file.read_text() == before


def test_seed_worktree_seeds_rules_present_in_global(
    tmp_path: Path,
    config: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(mod, "_load_global_allow_rules", lambda: ({"Bash(ls:*)"}, []))
    mod.seed_worktree(worktree_root=tmp_path, config=config)
    allow = _allow(tmp_path / ".claude" / "settings.local.json")
    assert "Bash(ls:*)" in allow
