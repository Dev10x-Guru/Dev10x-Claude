"""Tests for the ensure-scripts feature of update_paths module."""

import json
from pathlib import Path

import pytest

from dev10x.skills.permission import update_paths


class TestScanPluginScripts:
    @pytest.fixture()
    def plugin_root(self, tmp_path: Path) -> Path:
        root = tmp_path / "plugin"
        (root / "bin").mkdir(parents=True)
        (root / "bin" / "mktmp.sh").touch()
        (root / "bin" / "release.sh").touch()
        (root / "hooks" / "scripts").mkdir(parents=True)
        (root / "hooks" / "scripts" / "validate-bash-command.py").touch()
        (root / "skills" / "gh-context" / "scripts").mkdir(parents=True)
        (root / "skills" / "gh-context" / "scripts" / "detect-tracker.sh").touch()
        (root / "skills" / "gh-context" / "scripts" / "gh-pr-detect.sh").touch()
        return root

    def test_finds_bin_scripts(self, plugin_root: Path) -> None:
        result = update_paths.scan_plugin_scripts(plugin_root)

        names = [s.name for s in result]
        assert "mktmp.sh" in names
        assert "release.sh" in names

    def test_finds_hook_scripts(self, plugin_root: Path) -> None:
        result = update_paths.scan_plugin_scripts(plugin_root)

        names = [s.name for s in result]
        assert "validate-bash-command.py" in names

    def test_finds_skill_scripts(self, plugin_root: Path) -> None:
        result = update_paths.scan_plugin_scripts(plugin_root)

        names = [s.name for s in result]
        assert "detect-tracker.sh" in names
        assert "gh-pr-detect.sh" in names

    def test_returns_sorted_unique_paths(self, plugin_root: Path) -> None:
        result = update_paths.scan_plugin_scripts(plugin_root)

        assert result == sorted(set(result))

    def test_returns_empty_for_empty_plugin(self, tmp_path: Path) -> None:
        result = update_paths.scan_plugin_scripts(tmp_path)

        assert result == []


class TestBuildScriptAllowRules:
    def test_builds_bash_allow_rules(self, tmp_path: Path) -> None:
        plugin_root = tmp_path / "plugin"
        (plugin_root / "bin").mkdir(parents=True)
        script = plugin_root / "bin" / "mktmp.sh"
        script.touch()

        rules = update_paths.build_script_allow_rules(
            [script],
            plugin_root=plugin_root,
        )

        assert rules == [f"Bash({plugin_root}/bin/mktmp.sh:*)"]


class TestVerifyScriptCoverage:
    @pytest.fixture()
    def settings_file(self, tmp_path: Path) -> Path:
        return tmp_path / "settings.local.json"

    def test_detects_missing_scripts(self, settings_file: Path) -> None:
        settings_file.write_text(json.dumps({"permissions": {"allow": ["Bash(git log:*)"]}}))

        _covered, missing = update_paths.verify_script_coverage(
            settings_path=settings_file,
            expected_rules=["Bash(/cache/0.58.0/bin/mktmp.sh:*)"],
        )

        assert missing == ["Bash(/cache/0.58.0/bin/mktmp.sh:*)"]

    def test_detects_covered_by_exact_match(self, settings_file: Path) -> None:
        rule = "Bash(/cache/0.58.0/bin/mktmp.sh:*)"
        settings_file.write_text(json.dumps({"permissions": {"allow": [rule]}}))

        covered, missing = update_paths.verify_script_coverage(
            settings_path=settings_file,
            expected_rules=[rule],
        )

        assert covered == [rule]
        assert missing == []

    def test_detects_covered_by_script_name_match(self, settings_file: Path) -> None:
        settings_file.write_text(
            json.dumps({"permissions": {"allow": ["Bash(/old/path/bin/mktmp.sh:*)"]}})
        )

        covered, _missing = update_paths.verify_script_coverage(
            settings_path=settings_file,
            expected_rules=["Bash(/new/path/bin/mktmp.sh:*)"],
        )

        assert len(covered) == 1

    def test_glob_star_entry_is_not_coverage(self, settings_file: Path) -> None:
        # GH-471: a ** cache glob is non-functional in Claude Code's Bash
        # matcher and update-paths cannot re-version it (no literal X.Y.Z
        # segment). It must NOT count as coverage, so ensure-scripts emits
        # the concrete version-pinned rule instead of silently skipping it.
        dead_glob = "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/**/bin/mktmp.sh:*)"
        settings_file.write_text(json.dumps({"permissions": {"allow": [dead_glob]}}))
        concrete = "Bash(/home/u/.claude/plugins/cache/Dev10x-Guru/Dev10x/0.78.0/bin/mktmp.sh:*)"

        _covered, missing = update_paths.verify_script_coverage(
            settings_path=settings_file,
            expected_rules=[concrete],
        )

        assert missing == [concrete]

    def test_concrete_versioned_entry_at_other_path_is_coverage(self, settings_file: Path) -> None:
        # The version-bump case still counts as covered: a concrete path at
        # an older version is re-versioned by update-paths, so ensure-scripts
        # must not duplicate it.
        older = "Bash(/home/u/.claude/plugins/cache/Dev10x-Guru/Dev10x/0.77.0/bin/mktmp.sh:*)"
        settings_file.write_text(json.dumps({"permissions": {"allow": [older]}}))
        newer = "Bash(/home/u/.claude/plugins/cache/Dev10x-Guru/Dev10x/0.78.0/bin/mktmp.sh:*)"

        covered, missing = update_paths.verify_script_coverage(
            settings_path=settings_file,
            expected_rules=[newer],
        )

        assert covered == [newer]
        assert missing == []

    def test_no_false_positive_on_substring_match(self, settings_file: Path) -> None:
        settings_file.write_text(
            json.dumps({"permissions": {"allow": ["Bash(/path/test-utils.sh:*)"]}})
        )

        _covered, missing = update_paths.verify_script_coverage(
            settings_path=settings_file,
            expected_rules=["Bash(/cache/bin/test.sh:*)"],
        )

        assert len(missing) == 1

    def test_handles_invalid_json(self, settings_file: Path) -> None:
        settings_file.write_text("{invalid}")

        _covered, missing = update_paths.verify_script_coverage(
            settings_path=settings_file,
            expected_rules=["Bash(/cache/bin/mktmp.sh:*)"],
        )

        assert len(missing) == 1

    def test_handles_empty_allow_list(self, settings_file: Path) -> None:
        settings_file.write_text(json.dumps({"permissions": {"allow": []}}))

        _covered, missing = update_paths.verify_script_coverage(
            settings_path=settings_file,
            expected_rules=["Bash(/cache/bin/mktmp.sh:*)"],
        )

        assert len(missing) == 1


class TestEnsureScriptRules:
    @pytest.fixture()
    def settings_file(self, tmp_path: Path) -> Path:
        path = tmp_path / "settings.local.json"
        path.write_text(json.dumps({"permissions": {"allow": ["Bash(git log:*)"]}}))
        return path

    def test_adds_missing_rules(self, settings_file: Path) -> None:
        missing = ["Bash(/cache/bin/mktmp.sh:*)"]

        count, messages = update_paths.ensure_script_rules(
            settings_path=settings_file,
            missing_rules=missing,
        )

        assert count == 1
        data = json.loads(settings_file.read_text())
        assert "Bash(/cache/bin/mktmp.sh:*)" in data["permissions"]["allow"]
        assert "Bash(git log:*)" in data["permissions"]["allow"]

    def test_dry_run_does_not_write(self, settings_file: Path) -> None:
        original = settings_file.read_text()
        missing = ["Bash(/cache/bin/mktmp.sh:*)"]

        count, messages = update_paths.ensure_script_rules(
            settings_path=settings_file,
            missing_rules=missing,
            dry_run=True,
        )

        assert count == 1
        assert settings_file.read_text() == original

    def test_returns_zero_when_no_missing(self, settings_file: Path) -> None:
        count, messages = update_paths.ensure_script_rules(
            settings_path=settings_file,
            missing_rules=[],
        )

        assert count == 0
        assert messages == []


class TestIsDeadGlobScriptRule:
    def test_bash_cache_glob_is_dead(self) -> None:
        rule = "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/**/bin/mktmp.sh:*)"
        assert update_paths.is_dead_glob_script_rule(rule) is True

    def test_concrete_versioned_bash_rule_is_not_dead(self) -> None:
        rule = "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/0.78.0/bin/mktmp.sh:*)"
        assert update_paths.is_dead_glob_script_rule(rule) is False

    def test_read_marketplaces_glob_is_not_dead(self) -> None:
        # Read rules are functional with ** and must never be purged.
        rule = "Read(~/.claude/plugins/marketplaces/Dev10x-Guru/**)"
        assert update_paths.is_dead_glob_script_rule(rule) is False

    def test_non_cache_bash_glob_is_not_dead(self) -> None:
        rule = "Bash(/tmp/Dev10x/**/*.py:*)"
        assert update_paths.is_dead_glob_script_rule(rule) is False


class TestPurgeDeadGlobScriptRules:
    @pytest.fixture()
    def settings_file(self, tmp_path: Path) -> Path:
        return tmp_path / "settings.local.json"

    def test_removes_dead_glob_keeps_others(self, settings_file: Path) -> None:
        dead = "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/**/bin/mktmp.sh:*)"
        keep_read = "Read(~/.claude/plugins/marketplaces/Dev10x-Guru/**)"
        keep_bash = "Bash(git log:*)"
        settings_file.write_text(
            json.dumps({"permissions": {"allow": [dead, keep_read, keep_bash]}})
        )

        count, messages = update_paths.purge_dead_glob_script_rules(settings_file)

        assert count == 1
        assert len(messages) == 1
        allow = json.loads(settings_file.read_text())["permissions"]["allow"]
        assert dead not in allow
        assert keep_read in allow
        assert keep_bash in allow

    def test_returns_zero_when_no_dead_globs(self, settings_file: Path) -> None:
        settings_file.write_text(json.dumps({"permissions": {"allow": ["Bash(git log:*)"]}}))

        count, messages = update_paths.purge_dead_glob_script_rules(settings_file)

        assert count == 0
        assert messages == []

    def test_dry_run_does_not_write(self, settings_file: Path) -> None:
        dead = "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/**/bin/mktmp.sh:*)"
        settings_file.write_text(json.dumps({"permissions": {"allow": [dead]}}))
        original = settings_file.read_text()

        count, _messages = update_paths.purge_dead_glob_script_rules(settings_file, dry_run=True)

        assert count == 1
        assert settings_file.read_text() == original

    def test_handles_invalid_json(self, settings_file: Path) -> None:
        settings_file.write_text("{invalid}")

        count, messages = update_paths.purge_dead_glob_script_rules(settings_file)

        assert count == 0
        assert messages and "SKIP" in messages[0]


class TestEnsureScriptsReplacesDeadGlobs:
    def test_purges_dead_glob_and_adds_concrete(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        plugin_root = cache_dir / "0.78.0"
        (plugin_root / "bin").mkdir(parents=True)
        (plugin_root / "bin" / "mktmp.sh").touch()

        settings = tmp_path / "settings.local.json"
        dead = "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/**/bin/mktmp.sh:*)"
        settings.write_text(json.dumps({"permissions": {"allow": [dead]}}))

        result = update_paths.ensure_scripts(
            config={"plugin_cache": str(cache_dir)},
            settings_files=[settings],
            dry_run=False,
            quiet=True,
        )

        assert result["exit_code"] == 0
        allow = json.loads(settings.read_text())["permissions"]["allow"]
        assert dead not in allow
        assert f"Bash({plugin_root}/bin/mktmp.sh:*)" in allow


class TestEnsureScriptsFunction:
    @pytest.fixture()
    def cache_dir(self, tmp_path: Path) -> Path:
        cache = tmp_path / "cache"
        (cache / "0.78.0" / "bin").mkdir(parents=True)
        (cache / "0.78.0" / "bin" / "mktmp.sh").touch()
        return cache

    def _concrete(self, cache_dir: Path) -> str:
        return f"Bash({cache_dir / '0.78.0'}/bin/mktmp.sh:*)"

    def test_noop_when_already_covered(self, tmp_path: Path, cache_dir: Path) -> None:
        settings = tmp_path / "settings.local.json"
        settings.write_text(json.dumps({"permissions": {"allow": [self._concrete(cache_dir)]}}))
        original = settings.read_text()

        result = update_paths.ensure_scripts(
            config={"plugin_cache": str(cache_dir)},
            settings_files=[settings],
            dry_run=False,
            quiet=True,
        )

        assert result["files_changed"] == 0
        assert settings.read_text() == original
        assert any("complete script coverage" in m for m in result["messages"])

    def test_quiet_false_reports_messages(self, tmp_path: Path, cache_dir: Path) -> None:
        settings = tmp_path / "settings.local.json"
        dead = "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/**/bin/mktmp.sh:*)"
        settings.write_text(json.dumps({"permissions": {"allow": [dead]}}))

        result = update_paths.ensure_scripts(
            config={"plugin_cache": str(cache_dir)},
            settings_files=[settings],
            dry_run=False,
            quiet=False,
        )

        joined = "\n".join(result["messages"])
        assert "Plugin root:" in joined
        assert "dead ** cache glob removed" in joined
        assert "Updated 1 files" in joined

    def test_dry_run_reports_would_update(self, tmp_path: Path, cache_dir: Path) -> None:
        settings = tmp_path / "settings.local.json"
        dead = "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/**/bin/mktmp.sh:*)"
        settings.write_text(json.dumps({"permissions": {"allow": [dead]}}))
        original = settings.read_text()

        result = update_paths.ensure_scripts(
            config={"plugin_cache": str(cache_dir)},
            settings_files=[settings],
            dry_run=True,
            quiet=False,
        )

        assert settings.read_text() == original
        assert any("Would update" in m for m in result["messages"])

    def test_purges_when_concrete_already_present(self, tmp_path: Path, cache_dir: Path) -> None:
        settings = tmp_path / "settings.local.json"
        dead = "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/**/bin/mktmp.sh:*)"
        settings.write_text(
            json.dumps({"permissions": {"allow": [dead, self._concrete(cache_dir)]}})
        )

        result = update_paths.ensure_scripts(
            config={"plugin_cache": str(cache_dir)},
            settings_files=[settings],
            dry_run=False,
            quiet=True,
        )

        allow = json.loads(settings.read_text())["permissions"]["allow"]
        assert dead not in allow
        assert self._concrete(cache_dir) in allow
        assert result["files_changed"] == 1

    def test_errors_when_no_versions(self, tmp_path: Path) -> None:
        empty_cache = tmp_path / "empty-cache"
        empty_cache.mkdir()
        settings = tmp_path / "settings.local.json"
        settings.write_text(json.dumps({"permissions": {"allow": []}}))

        result = update_paths.ensure_scripts(
            config={"plugin_cache": str(empty_cache)},
            settings_files=[settings],
            dry_run=False,
            quiet=True,
        )

        assert result["exit_code"] == 1
        assert any("No versions found" in e for e in result["errors"])

    def test_reports_when_no_scripts(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache"
        (cache / "0.78.0").mkdir(parents=True)
        settings = tmp_path / "settings.local.json"
        settings.write_text(json.dumps({"permissions": {"allow": []}}))

        result = update_paths.ensure_scripts(
            config={"plugin_cache": str(cache)},
            settings_files=[settings],
            dry_run=False,
            quiet=True,
        )

        assert result["exit_code"] == 0
        assert any("No callable scripts" in m for m in result["messages"])
