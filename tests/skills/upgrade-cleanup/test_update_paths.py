"""Tests for update_paths.py: publisher rename, base permissions and
denies, script rules, dead-glob purging, legacy cleanup, generalization,
userspace config init, and workspace directories."""

import json
from pathlib import Path

import pytest

from dev10x.skills.permission import update_paths
from dev10x.skills.permission.update_paths import (
    build_script_allow_rules,
    collapse_legacy_upgrade_cleanup_rule,
    collapse_legacy_upgrade_cleanup_rules,
    ensure_base_denies,
    ensure_base_permissions,
    ensure_read_rules,
    ensure_script_rules,
    ensure_workspace_directories,
    extract_cache_publisher,
    find_settings_files,
    generalize_permission,
    generalize_permissions,
    init_userspace_config,
    is_dead_glob_script_rule,
    purge_dead_glob_script_rules,
    scan_plugin_scripts,
    update_file,
    verify_script_coverage,
)


def _write_settings(path: Path, *, allow: list[str] | None = None, **sections: object) -> Path:
    permissions: dict[str, object] = {}
    if allow is not None:
        permissions["allow"] = allow
    permissions.update(sections)
    path.write_text(json.dumps({"permissions": permissions}))
    return path


class TestExtractCachePublisher:
    @pytest.mark.parametrize(
        "plugin_cache,expected",
        [
            ("~/.claude/plugins/cache/Dev10x-Guru/Dev10x", "Dev10x-Guru"),
            ("~/.claude/plugins/cache/WooYek/Dev10x", "WooYek"),
            ("~/.claude/plugins/cache/Dev10x-Guru/dev10x-claude", "Dev10x-Guru"),
        ],
    )
    def test_extracts_publisher(self, plugin_cache: str, expected: str) -> None:
        assert extract_cache_publisher(plugin_cache) == expected

    def test_returns_none_for_invalid_path(self) -> None:
        assert extract_cache_publisher("/no/cache/here") is None

    def test_returns_none_for_path_ending_at_cache(self) -> None:
        assert extract_cache_publisher("~/.claude/plugins/cache") is None


class TestUpdateFilePublisher:
    @pytest.fixture()
    def settings_file(self, tmp_path: Path) -> Path:
        return tmp_path / "settings.local.json"

    def test_replaces_stale_publisher(self, settings_file: Path) -> None:
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "Bash(~/.claude/plugins/cache/WooYek/Dev10x/0.48.0/skills/foo.sh:*)",
                        ]
                    }
                }
            )
        )

        count, messages = update_file(
            settings_file,
            target_version="0.54.0",
            target_publisher="Dev10x-Guru",
        )

        assert count == 1
        data = json.loads(settings_file.read_text())
        rule = data["permissions"]["allow"][0]
        assert "Dev10x-Guru/Dev10x/0.54.0" in rule
        assert "WooYek" not in rule

    def test_replaces_publisher_only_when_version_matches(
        self,
        settings_file: Path,
    ) -> None:
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "Bash(~/.claude/plugins/cache/WooYek/Dev10x/0.54.0/skills/foo.sh:*)",
                        ]
                    }
                }
            )
        )

        count, messages = update_file(
            settings_file,
            target_version="0.54.0",
            target_publisher="Dev10x-Guru",
        )

        assert count == 1
        data = json.loads(settings_file.read_text())
        rule = data["permissions"]["allow"][0]
        assert "Dev10x-Guru/Dev10x/0.54.0" in rule

    def test_no_changes_when_publisher_and_version_match(
        self,
        settings_file: Path,
    ) -> None:
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/0.54.0/skills/foo.sh:*)",
                        ]
                    }
                }
            )
        )

        count, messages = update_file(
            settings_file,
            target_version="0.54.0",
            target_publisher="Dev10x-Guru",
        )

        assert count == 0

    def test_skips_publisher_replacement_when_not_specified(
        self,
        settings_file: Path,
    ) -> None:
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "Bash(~/.claude/plugins/cache/WooYek/Dev10x/0.48.0/skills/foo.sh:*)",
                        ]
                    }
                }
            )
        )

        count, messages = update_file(
            settings_file,
            target_version="0.54.0",
        )

        assert count == 1
        data = json.loads(settings_file.read_text())
        rule = data["permissions"]["allow"][0]
        assert "WooYek/Dev10x/0.54.0" in rule

    def test_matches_dev10x_claude_plugin_name(self, settings_file: Path) -> None:
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "Bash(~/.claude/plugins/cache/WooYek/dev10x-claude/0.30.0/scripts/x.sh:*)",
                        ]
                    }
                }
            )
        )

        count, messages = update_file(
            settings_file,
            target_version="0.54.0",
            target_publisher="Dev10x-Guru",
        )

        assert count == 1
        data = json.loads(settings_file.read_text())
        rule = data["permissions"]["allow"][0]
        assert "Dev10x-Guru/dev10x-claude/0.54.0" in rule

    def test_replaces_multiple_rules_in_same_file(
        self,
        settings_file: Path,
    ) -> None:
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "Bash(~/.claude/plugins/cache/WooYek/Dev10x/0.48.0/skills/a.sh:*)",
                            "Bash(git log:*)",
                            "Bash(~/.claude/plugins/cache/WooYek/Dev10x/0.48.0/skills/b.sh:*)",
                        ]
                    }
                }
            )
        )

        count, messages = update_file(
            settings_file,
            target_version="0.54.0",
            target_publisher="Dev10x-Guru",
        )

        assert count == 2
        data = json.loads(settings_file.read_text())
        offenders = [rule for rule in data["permissions"]["allow"] if "WooYek" in rule]
        assert not offenders, f"WooYek not stripped from: {offenders}"

    def test_leaves_already_current_rule_untouched(self, settings_file: Path) -> None:
        # Mixed file: one stale rule (drives the locked rewrite) plus one
        # already-current rule (exercises the no-change branch of the
        # locked re-apply without inflating the change count).
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "Bash(~/.claude/plugins/cache/WooYek/Dev10x/0.48.0/skills/a.sh:*)",
                            "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/0.54.0/skills/b.sh:*)",
                        ]
                    }
                }
            )
        )

        count, _ = update_file(
            settings_file,
            target_version="0.54.0",
            target_publisher="Dev10x-Guru",
        )

        assert count == 1
        allow = json.loads(settings_file.read_text())["permissions"]["allow"]
        assert "Dev10x-Guru/Dev10x/0.54.0/skills/a.sh" in allow[0]
        assert "Dev10x-Guru/Dev10x/0.54.0/skills/b.sh" in allow[1]

    def test_dry_run_does_not_write(self, settings_file: Path) -> None:
        content = json.dumps(
            {
                "permissions": {
                    "allow": [
                        "Bash(~/.claude/plugins/cache/WooYek/Dev10x/0.48.0/skills/foo.sh:*)",
                    ]
                }
            }
        )
        settings_file.write_text(content)

        count, messages = update_file(
            settings_file,
            target_version="0.54.0",
            target_publisher="Dev10x-Guru",
            dry_run=True,
        )

        assert count == 1
        assert settings_file.read_text() == content


class TestFindSettingsFilesUserGlobal:
    """Regression: ~/.claude/settings.json was skipped by find_settings_files
    when include_user=True (Dev10x-Claude2#982). Both user-global files must
    be discovered so versioned plugin paths are rewritten there too."""

    @pytest.fixture()
    def fake_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
        return home

    def test_includes_both_user_global_files_when_include_user(
        self,
        fake_home: Path,
    ) -> None:
        local = fake_home / ".claude" / "settings.local.json"
        global_ = fake_home / ".claude" / "settings.json"
        local.write_text("{}")
        global_.write_text("{}")

        files = find_settings_files(roots=[], include_user=True)

        assert local.resolve() in files
        assert global_.resolve() in files

    def test_includes_settings_json_even_when_local_missing(
        self,
        fake_home: Path,
    ) -> None:
        global_ = fake_home / ".claude" / "settings.json"
        global_.write_text("{}")

        files = find_settings_files(roots=[], include_user=True)

        assert global_.resolve() in files

    def test_skips_user_global_files_when_include_user_false(
        self,
        fake_home: Path,
    ) -> None:
        (fake_home / ".claude" / "settings.json").write_text("{}")
        (fake_home / ".claude" / "settings.local.json").write_text("{}")

        files = find_settings_files(roots=[], include_user=False)

        assert files == []


class TestInitUserspaceConfig:
    @pytest.fixture()
    def config_paths(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[Path, Path, Path]:
        memory = tmp_path / "projects.yaml"
        userspace = tmp_path / "upgrade-cleanup-projects.yaml"
        plugin = tmp_path / "plugin-projects.yaml"
        monkeypatch.setattr(update_paths, "MEMORY_CONFIG", memory)
        monkeypatch.setattr(update_paths, "USERSPACE_CONFIG", userspace)
        monkeypatch.setattr(update_paths, "PLUGIN_CONFIG", plugin)
        return memory, userspace, plugin

    def test_noop_when_projects_yaml_exists(self, config_paths: tuple[Path, Path, Path]) -> None:
        memory, _userspace, _plugin = config_paths
        memory.write_text("roots: [/work/existing]\n")

        result = init_userspace_config()

        assert result["exit_code"] == 0
        assert memory.read_text() == "roots: [/work/existing]\n"
        assert any("already exists" in m for m in result["messages"])

    def test_migrates_legacy_userspace_into_projects_yaml(
        self, config_paths: tuple[Path, Path, Path]
    ) -> None:
        memory, userspace, _plugin = config_paths
        userspace.write_text("roots: [/work/legacy]\n")

        result = init_userspace_config()

        assert result["exit_code"] == 0
        assert memory.read_text() == "roots: [/work/legacy]\n"
        assert userspace.exists()  # left in place for downgrade safety
        assert any("Migrated" in m for m in result["messages"])

    def test_creates_from_plugin_default_when_none_exist(
        self,
        config_paths: tuple[Path, Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        memory, _userspace, plugin = config_paths
        plugin.write_text("plugin_cache: ~/.claude/plugins/cache/Dev10x-Guru/dev10x-claude\n")
        monkeypatch.setattr(update_paths, "_detect_plugin_cache", lambda: "/detected/cache")

        result = init_userspace_config()

        assert result["exit_code"] == 0
        assert "plugin_cache: /detected/cache" in memory.read_text()
        assert any("Created" in m for m in result["messages"])

    def test_errors_when_plugin_default_missing(
        self, config_paths: tuple[Path, Path, Path]
    ) -> None:
        result = init_userspace_config()

        assert result["exit_code"] == 1
        assert any("Plugin default config not found" in e for e in result["errors"])

    def test_rechecks_inside_lock_when_config_appears(
        self,
        config_paths: tuple[Path, Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Double-checked locking (GH-587): a config that appears between the
        outer check and the lock must not be clobbered."""
        from contextlib import contextmanager

        memory, userspace, _plugin = config_paths
        userspace.write_text("roots: [/work/legacy]\n")

        @contextmanager
        def racing_lock(path: Path, **_: object):
            memory.write_text("roots: [/work/winner]\n")
            yield

        monkeypatch.setattr("dev10x.domain.file_locks.file_lock", racing_lock)

        result = init_userspace_config()

        assert result["exit_code"] == 0
        assert memory.read_text() == "roots: [/work/winner]\n"
        assert any("already exists" in m for m in result["messages"])


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


class TestScanPluginScripts:
    def test_finds_scripts_across_globs(self, tmp_path: Path) -> None:
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "release.sh").write_text("#!/bin/sh\n")
        (tmp_path / "hooks" / "scripts").mkdir(parents=True)
        (tmp_path / "hooks" / "scripts" / "hook.py").write_text("")
        (tmp_path / "skills" / "foo" / "scripts").mkdir(parents=True)
        (tmp_path / "skills" / "foo" / "scripts" / "run.sh").write_text("")

        scripts = scan_plugin_scripts(tmp_path)

        names = {p.name for p in scripts}
        assert names == {"release.sh", "hook.py", "run.sh"}

    def test_returns_sorted_unique(self, tmp_path: Path) -> None:
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "a.sh").write_text("")
        (tmp_path / "bin" / "b.sh").write_text("")
        scripts = scan_plugin_scripts(tmp_path)
        assert scripts == sorted(scripts)

    def test_empty_when_no_scripts(self, tmp_path: Path) -> None:
        assert scan_plugin_scripts(tmp_path) == []


class TestBuildScriptAllowRules:
    def test_builds_bash_rule_per_script(self, tmp_path: Path) -> None:
        (tmp_path / "bin").mkdir()
        script = tmp_path / "bin" / "release.sh"
        script.write_text("")
        rules = build_script_allow_rules([script], plugin_root=tmp_path)
        assert rules == [f"Bash({tmp_path}/bin/release.sh:*)"]

    def test_empty_for_no_scripts(self, tmp_path: Path) -> None:
        assert build_script_allow_rules([], plugin_root=tmp_path) == []


class TestIsDeadGlobScriptRule:
    @pytest.mark.parametrize(
        "entry",
        [
            "Bash(~/.claude/plugins/cache/Pub/Plug/**/scripts/x.sh:*)",
            "Bash(/home/u/.claude/plugins/cache/Pub/Plug/**:*)",
        ],
    )
    def test_true_for_dead_glob(self, entry: str) -> None:
        assert is_dead_glob_script_rule(entry) is True

    @pytest.mark.parametrize(
        "entry",
        [
            "Bash(~/.claude/plugins/cache/Pub/Plug/0.1.0/scripts/x.sh:*)",
            "Read(~/.claude/plugins/marketplaces/Pub/**)",
            "Bash(git status:*)",
        ],
    )
    def test_false_for_functional_rule(self, entry: str) -> None:
        assert is_dead_glob_script_rule(entry) is False


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


class TestVerifyScriptCoverage:
    def test_reports_covered_and_missing(self, tmp_path: Path) -> None:
        path = _write_settings(
            tmp_path / "settings.local.json",
            allow=["Bash(/any/path/release.sh:*)"],
        )
        covered, missing = verify_script_coverage(
            path,
            ["Bash(/plugin/bin/release.sh:*)", "Bash(/plugin/bin/other.sh:*)"],
        )
        assert covered == ["Bash(/plugin/bin/release.sh:*)"]
        assert missing == ["Bash(/plugin/bin/other.sh:*)"]

    def test_exact_match_counts_as_covered(self, tmp_path: Path) -> None:
        rule = "Bash(/plugin/bin/release.sh:*)"
        path = _write_settings(tmp_path / "settings.local.json", allow=[rule])
        covered, missing = verify_script_coverage(path, [rule])
        assert covered == [rule]
        assert missing == []

    def test_dead_glob_is_not_coverage(self, tmp_path: Path) -> None:
        path = _write_settings(
            tmp_path / "settings.local.json",
            allow=["Bash(~/.claude/plugins/cache/Pub/Plug/**/release.sh:*)"],
        )
        covered, missing = verify_script_coverage(path, ["Bash(/plugin/bin/release.sh:*)"])
        assert covered == []
        assert missing == ["Bash(/plugin/bin/release.sh:*)"]

    def test_invalid_json_treats_all_as_missing(self, tmp_path: Path) -> None:
        bad = tmp_path / "settings.local.json"
        bad.write_text("{invalid")
        covered, missing = verify_script_coverage(bad, ["Bash(x:*)"])
        assert covered == []
        assert missing == ["Bash(x:*)"]


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


class TestGeneralizePermission:
    @pytest.mark.parametrize(
        ("entry", "expected"),
        [
            ("Bash(/p/foo.sh arg1 arg2:*)", "Bash(/p/foo.sh:*)"),
            ("Bash(/p/run.py --flag value:*)", "Bash(/p/run.py:*)"),
            ("Bash(git reset --soft abc123def0:*)", "Bash(git reset --soft:*)"),
        ],
    )
    def test_generalizes_known_patterns(self, entry: str, expected: str) -> None:
        assert generalize_permission(entry) == expected

    def test_returns_none_when_no_change(self) -> None:
        assert generalize_permission("Bash(git status:*)") is None


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
