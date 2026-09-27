"""GH-1501: ``clean`` migrates pre-rename rule spellings in every layer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR
from dev10x.skills.permission import clean_project_files as clean_mod

LEGACY_DENY = "mcp__plugin_Dev10x_cli__merge_pr"
CURRENT_DENY = "mcp__plugin_dev10x_cli__merge_pr"


def _write(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) + "\n")
    return path


def _read(path: Path) -> dict:
    return json.loads(path.read_text())


def _clean(path: Path, *, dry_run: bool = False) -> tuple:
    return clean_mod.clean_file(
        path,
        global_rules=set(),
        current_version=None,
        dry_run=dry_run,
    )


class TestCleanFile:
    def test_deny_only_file_is_migrated(self, tmp_path: Path) -> None:
        # No allow list at all — the pre-GH-1501 early return skipped this.
        path = _write(tmp_path / "settings.local.json", {"permissions": {"deny": [LEGACY_DENY]}})

        result, _ = _clean(path)

        assert _read(path)["permissions"]["deny"] == [CURRENT_DENY]
        assert result.namespace_migration.count == 1

    def test_migration_and_pruning_land_together(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path / "settings.local.json",
            {
                "permissions": {
                    "allow": ["Skill(Dev10x:git)", "Bash(do)"],
                    "deny": [LEGACY_DENY],
                },
                "enabledPlugins": {"Dev10x@Dev10x-Guru": True},
            },
        )

        _clean(path)

        assert _read(path) == {
            "permissions": {"allow": ["Skill(dev10x:git)"], "deny": [CURRENT_DENY]},
            "enabledPlugins": {"dev10x@Dev10x-Guru": True},
        }

    def test_a_backup_is_written_first(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "settings.local.json", {"permissions": {"deny": [LEGACY_DENY]}})

        _clean(path)

        assert len(list(tmp_path.glob("settings.local.json.bak.*"))) == 1

    def test_dry_run_reports_without_writing(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "settings.local.json", {"permissions": {"deny": [LEGACY_DENY]}})
        original = path.read_text()

        _, messages = _clean(path, dry_run=True)

        assert path.read_text() == original
        assert f"    deny: {LEGACY_DENY} -> {CURRENT_DENY}" in messages

    def test_second_run_is_a_no_op(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "settings.local.json", {"permissions": {"deny": [LEGACY_DENY]}})
        _clean(path)
        after_first = path.read_text()

        result, messages = _clean(path)

        assert path.read_text() == after_first
        assert result.namespace_migration.changed is False
        assert messages == []


class TestMigrateFile:
    def test_rewrites_without_pruning_anything_else(self, tmp_path: Path) -> None:
        # User-scope layer: shell fragments and global duplicates are not
        # clean's to prune here — only the namespace moves.
        path = _write(
            tmp_path / "settings.json",
            {"permissions": {"allow": ["Bash(do)", "Skill(Dev10x:git)"], "deny": [LEGACY_DENY]}},
        )

        result, messages = clean_mod.migrate_file(path)

        assert _read(path)["permissions"] == {
            "allow": ["Bash(do)", "Skill(dev10x:git)"],
            "deny": [CURRENT_DENY],
        }
        assert result.namespace_migration.count == 2
        assert messages[0] == "  - 2 rules moved to the dev10x namespace (GH-1501)"

    def test_clean_layer_is_untouched(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "settings.json", {"permissions": {"deny": [CURRENT_DENY]}})
        original = path.read_text()

        result, messages = clean_mod.migrate_file(path)

        assert path.read_text() == original
        assert result.namespace_migration.changed is False
        assert messages == []

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "settings.json", {"permissions": {"deny": [LEGACY_DENY]}})
        original = path.read_text()

        clean_mod.migrate_file(path, dry_run=True)

        assert path.read_text() == original

    def test_invalid_json_is_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        path.write_text("{not json")

        result, messages = clean_mod.migrate_file(path)

        assert result is None
        assert "SKIP" in messages[0]


class TestNamespaceMigrationLayers:
    @pytest.fixture
    def claude_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        home = tmp_path / "home" / ".claude"
        home.mkdir(parents=True)
        monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(home))
        return home

    def test_user_scope_and_committed_project_layers_are_included(
        self, tmp_path: Path, claude_home: Path
    ) -> None:
        user = _write(claude_home / "settings.json", {})
        user_local = _write(claude_home / "settings.local.json", {})
        project_local = _write(tmp_path / "proj" / ".claude" / "settings.local.json", {})
        project_shared = _write(tmp_path / "proj" / ".claude" / "settings.json", {})

        layers = clean_mod.namespace_migration_layers(settings_files=[project_local.resolve()])

        assert layers == [user.resolve(), user_local.resolve(), project_shared.resolve()]

    def test_missing_and_already_scanned_files_are_skipped(
        self, tmp_path: Path, claude_home: Path
    ) -> None:
        user_local = _write(claude_home / "settings.local.json", {})
        orphan_local = _write(tmp_path / "orphan" / ".claude" / "settings.local.json", {})

        layers = clean_mod.namespace_migration_layers(
            settings_files=[user_local.resolve(), orphan_local.resolve()]
        )

        assert layers == []


class TestRunClean:
    def test_migration_layers_are_migrated_and_counted(self, tmp_path: Path) -> None:
        project = _write(tmp_path / "p" / "settings.local.json", {"permissions": {"allow": []}})
        layer = _write(tmp_path / "u" / "settings.json", {"permissions": {"deny": [LEGACY_DENY]}})

        run = clean_mod.run_clean(
            settings_files=[project],
            global_rules=set(),
            current_version=None,
            base_permissions=set(),
            cache_root=None,
            dry_run=False,
            verbose=False,
            skip_global_dedup=True,
            migration_layers=[layer],
        )

        assert run.total_migrated == 1
        assert run.files_changed == 1
        assert run.total_removed == 0
        assert _read(layer)["permissions"]["deny"] == [CURRENT_DENY]
