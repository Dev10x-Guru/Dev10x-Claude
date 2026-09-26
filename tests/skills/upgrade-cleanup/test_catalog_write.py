"""Tests for catalog_write.py: the ensure_* fixers, generalize, and legacy-
rule collapse that mutate settings files in place (GH-1432, GH-1449).

`ensure_base` / `seed_worktree` / `catalog_gap` have their own dedicated
files (test_ensure_base.py, test_seed_worktree.py, test_catalog_gap.py) —
this file covers the writers that were only exercised via the monolithic
update_paths test file."""

import json
from pathlib import Path

import pytest

from dev10x.skills.permission.catalog_write import (
    collapse_legacy_upgrade_cleanup_rule,
    collapse_legacy_upgrade_cleanup_rules,
    ensure_base_denies,
    ensure_base_permissions,
    ensure_read_rules,
    ensure_script_rules,
    ensure_workspace_directories,
    generalize_permissions,
    purge_dead_glob_script_rules,
)


def _write_settings(path: Path, *, allow: list[str] | None = None, **sections: object) -> Path:
    permissions: dict[str, object] = {}
    if allow is not None:
        permissions["allow"] = allow
    permissions.update(sections)
    path.write_text(json.dumps({"permissions": permissions}))
    return path


class TestEnsureBasePermissions:
    @pytest.fixture()
    def settings_file(self, tmp_path: Path) -> Path:
        return _write_settings(tmp_path / "settings.local.json", allow=[])

    def test_adds_missing_permission(self, settings_file: Path) -> None:
        count, messages = ensure_base_permissions(
            settings_file, ["Bash(git status:*)"], expand_mcp=False
        )
        assert count == 1
        data = json.loads(settings_file.read_text())
        assert "Bash(git status:*)" in data["permissions"]["allow"]

    def test_noop_when_present(self, settings_file: Path) -> None:
        _write_settings(settings_file, allow=["Bash(git status:*)"])
        count, messages = ensure_base_permissions(
            settings_file, ["Bash(git status:*)"], expand_mcp=False
        )
        assert count == 0
        assert messages == []

    def test_dry_run_does_not_write(self, settings_file: Path) -> None:
        count, _ = ensure_base_permissions(
            settings_file, ["Bash(git status:*)"], dry_run=True, expand_mcp=False
        )
        assert count == 1
        data = json.loads(settings_file.read_text())
        assert data["permissions"]["allow"] == []

    def test_invalid_json_skips(self, tmp_path: Path) -> None:
        bad = tmp_path / "settings.local.json"
        bad.write_text("{invalid")
        count, messages = ensure_base_permissions(bad, ["Bash(git:*)"], expand_mcp=False)
        assert count == 0
        assert messages and "SKIP" in messages[0]

    def test_removes_nonfunctional_mcp_wildcard(self, settings_file: Path) -> None:
        _write_settings(settings_file, allow=["mcp__plugin_Dev10x_*"])
        count, _ = ensure_base_permissions(settings_file, [], expand_mcp=False)
        assert count == 1
        data = json.loads(settings_file.read_text())
        assert "mcp__plugin_Dev10x_*" not in data["permissions"]["allow"]


class TestEnsureBaseDenies:
    @pytest.fixture()
    def settings_file(self, tmp_path: Path) -> Path:
        return _write_settings(tmp_path / "settings.local.json", deny=[])

    def test_adds_missing_deny(self, settings_file: Path) -> None:
        count, _ = ensure_base_denies(settings_file, ["Bash(rm -rf /:*)"])
        assert count == 1
        data = json.loads(settings_file.read_text())
        assert "Bash(rm -rf /:*)" in data["permissions"]["deny"]

    def test_noop_when_present(self, settings_file: Path) -> None:
        _write_settings(settings_file, deny=["Bash(rm -rf /:*)"])
        count, messages = ensure_base_denies(settings_file, ["Bash(rm -rf /:*)"])
        assert count == 0
        assert messages == []

    def test_dry_run_does_not_write(self, settings_file: Path) -> None:
        count, _ = ensure_base_denies(settings_file, ["Bash(rm -rf /:*)"], dry_run=True)
        assert count == 1
        data = json.loads(settings_file.read_text())
        assert data["permissions"]["deny"] == []

    def test_invalid_json_skips(self, tmp_path: Path) -> None:
        bad = tmp_path / "settings.local.json"
        bad.write_text("{invalid")
        count, messages = ensure_base_denies(bad, ["Bash(x:*)"])
        assert count == 0
        assert messages and "SKIP" in messages[0]


class TestPurgeDeadGlobScriptRules:
    def test_removes_dead_glob(self, tmp_path: Path) -> None:
        path = _write_settings(
            tmp_path / "settings.local.json",
            allow=[
                "Bash(~/.claude/plugins/cache/Pub/Plug/**:*)",
                "Bash(git status:*)",
            ],
        )
        count, _ = purge_dead_glob_script_rules(path)
        assert count == 1
        data = json.loads(path.read_text())
        assert data["permissions"]["allow"] == ["Bash(git status:*)"]

    def test_noop_without_dead_globs(self, tmp_path: Path) -> None:
        path = _write_settings(tmp_path / "settings.local.json", allow=["Bash(git status:*)"])
        count, messages = purge_dead_glob_script_rules(path)
        assert count == 0
        assert messages == []

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        path = _write_settings(
            tmp_path / "settings.local.json",
            allow=["Bash(~/.claude/plugins/cache/Pub/Plug/**:*)"],
        )
        count, _ = purge_dead_glob_script_rules(path, dry_run=True)
        assert count == 1
        data = json.loads(path.read_text())
        assert len(data["permissions"]["allow"]) == 1

    def test_unreadable_json_skips(self, tmp_path: Path) -> None:
        bad = tmp_path / "settings.local.json"
        bad.write_text("{invalid")
        count, messages = purge_dead_glob_script_rules(bad)
        assert count == 0
        assert messages and "SKIP" in messages[0]


class TestEnsureReadRules:
    def test_appends_missing_idempotently(self, tmp_path: Path) -> None:
        path = _write_settings(tmp_path / "settings.local.json", allow=["Read(~/a/*)"])
        count, _ = ensure_read_rules(path, ["Read(~/a/*)", "Read(~/b/*)"])
        assert count == 2
        data = json.loads(path.read_text())
        assert data["permissions"]["allow"].count("Read(~/a/*)") == 1
        assert "Read(~/b/*)" in data["permissions"]["allow"]

    def test_empty_rules_noop(self, tmp_path: Path) -> None:
        path = _write_settings(tmp_path / "settings.local.json", allow=[])
        assert ensure_read_rules(path, []) == (0, [])

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        path = _write_settings(tmp_path / "settings.local.json", allow=[])
        count, _ = ensure_read_rules(path, ["Read(~/b/*)"], dry_run=True)
        assert count == 1
        data = json.loads(path.read_text())
        assert data["permissions"]["allow"] == []


class TestEnsureScriptRules:
    def test_extends_allow(self, tmp_path: Path) -> None:
        path = _write_settings(tmp_path / "settings.local.json", allow=[])
        count, _ = ensure_script_rules(path, ["Bash(/p/x.sh:*)"])
        assert count == 1
        data = json.loads(path.read_text())
        assert "Bash(/p/x.sh:*)" in data["permissions"]["allow"]

    def test_empty_rules_noop(self, tmp_path: Path) -> None:
        path = _write_settings(tmp_path / "settings.local.json", allow=[])
        assert ensure_script_rules(path, []) == (0, [])

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        path = _write_settings(tmp_path / "settings.local.json", allow=[])
        count, _ = ensure_script_rules(path, ["Bash(/p/x.sh:*)"], dry_run=True)
        assert count == 1
        data = json.loads(path.read_text())
        assert data["permissions"]["allow"] == []


class TestGeneralizePermissions:
    def test_rewrites_in_file(self, tmp_path: Path) -> None:
        path = _write_settings(
            tmp_path / "settings.local.json",
            allow=["Bash(/p/foo.sh arg1:*)"],
        )
        count, _ = generalize_permissions(path)
        assert count == 1
        data = json.loads(path.read_text())
        assert "Bash(/p/foo.sh:*)" in data["permissions"]["allow"]

    def test_empty_allow_noop(self, tmp_path: Path) -> None:
        path = _write_settings(tmp_path / "settings.local.json", allow=[])
        assert generalize_permissions(path) == (0, [])

    def test_no_replacements_noop(self, tmp_path: Path) -> None:
        path = _write_settings(tmp_path / "settings.local.json", allow=["Bash(git status:*)"])
        assert generalize_permissions(path) == (0, [])

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        path = _write_settings(tmp_path / "settings.local.json", allow=["Bash(/p/foo.sh arg1:*)"])
        count, _ = generalize_permissions(path, dry_run=True)
        assert count == 1
        data = json.loads(path.read_text())
        assert data["permissions"]["allow"] == ["Bash(/p/foo.sh arg1:*)"]

    def test_invalid_json_skips(self, tmp_path: Path) -> None:
        bad = tmp_path / "settings.local.json"
        bad.write_text("{invalid")
        count, messages = generalize_permissions(bad)
        assert count == 0
        assert messages and "SKIP" in messages[0]


class TestCollapseLegacyUpgradeCleanupRule:
    @pytest.mark.parametrize(
        ("entry", "expected"),
        [
            (
                "Bash(${CLAUDE_PLUGIN_ROOT}/skills/upgrade-cleanup/scripts/update-paths.py:*)",
                "Bash(uvx dev10x permission update-paths:*)",
            ),
            (
                "Bash(~/.claude/plugins/cache/Pub/Plug/0.1.0/skills/upgrade-cleanup/scripts/enumerate-mcp.py:*)",
                "Bash(uvx dev10x permission enumerate-mcp:*)",
            ),
        ],
    )
    def test_collapses_legacy_script(self, entry: str, expected: str) -> None:
        assert collapse_legacy_upgrade_cleanup_rule(entry) == expected

    def test_returns_none_for_unrelated(self) -> None:
        assert collapse_legacy_upgrade_cleanup_rule("Bash(git status:*)") is None

    def test_returns_none_for_unknown_script(self) -> None:
        entry = "Bash(${CLAUDE_PLUGIN_ROOT}/skills/upgrade-cleanup/scripts/unknown.py:*)"
        assert collapse_legacy_upgrade_cleanup_rule(entry) is None


class TestCollapseLegacyUpgradeCleanupRules:
    def test_rewrites_and_dedupes(self, tmp_path: Path) -> None:
        path = _write_settings(
            tmp_path / "settings.local.json",
            allow=[
                "Bash(${CLAUDE_PLUGIN_ROOT}/skills/upgrade-cleanup/scripts/update-paths.py:*)",
                "Bash(git status:*)",
            ],
        )
        count, _ = collapse_legacy_upgrade_cleanup_rules(path)
        assert count == 1
        data = json.loads(path.read_text())
        assert "Bash(uvx dev10x permission update-paths:*)" in data["permissions"]["allow"]
        assert "Bash(git status:*)" in data["permissions"]["allow"]

    def test_empty_allow_noop(self, tmp_path: Path) -> None:
        path = _write_settings(tmp_path / "settings.local.json", allow=[])
        assert collapse_legacy_upgrade_cleanup_rules(path) == (0, [])

    def test_no_replacements_noop(self, tmp_path: Path) -> None:
        path = _write_settings(tmp_path / "settings.local.json", allow=["Bash(git status:*)"])
        assert collapse_legacy_upgrade_cleanup_rules(path) == (0, [])

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        entry = "Bash(${CLAUDE_PLUGIN_ROOT}/skills/upgrade-cleanup/scripts/update-paths.py:*)"
        path = _write_settings(tmp_path / "settings.local.json", allow=[entry])
        count, _ = collapse_legacy_upgrade_cleanup_rules(path, dry_run=True)
        assert count == 1
        data = json.loads(path.read_text())
        assert data["permissions"]["allow"] == [entry]

    def test_unreadable_json_skips(self, tmp_path: Path) -> None:
        bad = tmp_path / "settings.local.json"
        bad.write_text("{invalid")
        count, messages = collapse_legacy_upgrade_cleanup_rules(bad)
        assert count == 0
        assert messages and "SKIP" in messages[0]


class TestEnsureWorkspaceDirectories:
    def test_adds_missing_directory(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.local.json"
        path.write_text(json.dumps({"permissions": {"additionalDirectories": []}}))
        count, _ = ensure_workspace_directories(path, ["/tmp/Dev10x"])
        assert count == 1
        data = json.loads(path.read_text())
        assert "/tmp/Dev10x" in data["permissions"]["additionalDirectories"]

    def test_noop_when_present(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.local.json"
        path.write_text(json.dumps({"permissions": {"additionalDirectories": ["/tmp/Dev10x"]}}))
        count, messages = ensure_workspace_directories(path, ["/tmp/Dev10x"])
        assert count == 0
        assert messages == []

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.local.json"
        path.write_text(json.dumps({"permissions": {"additionalDirectories": []}}))
        count, _ = ensure_workspace_directories(path, ["/tmp/Dev10x"], dry_run=True)
        assert count == 1
        data = json.loads(path.read_text())
        assert data["permissions"]["additionalDirectories"] == []

    def test_invalid_json_skips(self, tmp_path: Path) -> None:
        bad = tmp_path / "settings.local.json"
        bad.write_text("{invalid")
        count, messages = ensure_workspace_directories(bad, ["/tmp/Dev10x"])
        assert count == 0
        assert messages and "SKIP" in messages[0]
