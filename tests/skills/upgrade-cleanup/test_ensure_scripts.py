"""Tests for the ensure-scripts feature of update_paths module."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from dev10x.core.plugin_map import PluginMap
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

    def test_adds_missing_rules(
        self,
        settings_file: Path,
        read_allow: Callable[[Path], list[str]],
    ) -> None:
        missing = ["Bash(/cache/bin/mktmp.sh:*)"]

        count, messages = update_paths.ensure_script_rules(
            settings_path=settings_file,
            missing_rules=missing,
        )

        assert count == 1
        allow = read_allow(settings_file)
        assert "Bash(/cache/bin/mktmp.sh:*)" in allow
        assert "Bash(git log:*)" in allow

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

    def test_removes_dead_glob_keeps_others(
        self,
        settings_file: Path,
        read_allow: Callable[[Path], list[str]],
    ) -> None:
        dead = "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/**/bin/mktmp.sh:*)"
        keep_read = "Read(~/.claude/plugins/marketplaces/Dev10x-Guru/**)"
        keep_bash = "Bash(git log:*)"
        settings_file.write_text(
            json.dumps({"permissions": {"allow": [dead, keep_read, keep_bash]}})
        )

        count, messages = update_paths.purge_dead_glob_script_rules(settings_file)

        assert count == 1
        assert len(messages) == 1
        allow = read_allow(settings_file)
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
    def test_purges_dead_glob_and_adds_concrete(
        self,
        tmp_path: Path,
        read_allow: Callable[[Path], list[str]],
    ) -> None:
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
        allow = read_allow(settings)
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

    def test_purges_when_concrete_already_present(
        self,
        tmp_path: Path,
        cache_dir: Path,
        read_allow: Callable[[Path], list[str]],
    ) -> None:
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

        allow = read_allow(settings)
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


# ── GH-1807: satellite plugins seed their own script and Read grants ────

@pytest.fixture()
def satellite_plugin_map(make_plugin_map: Callable[..., PluginMap]) -> PluginMap:
    return make_plugin_map(
        plugins={"qa": ["tts"], "infra": ["k8s"]},
        plugin_names={"qa": "dev10x-qa", "infra": "dev10x-infra"},
    )


@pytest.fixture()
def empty_core_cache(make_plugin_cache: Callable[..., Path]) -> Path:
    root = make_plugin_cache(plugin_name="dev10x", version="0.115.0")
    (root / "skills" / "ask").mkdir(parents=True)
    return root.parent


@pytest.fixture()
def core_cache(empty_core_cache: Path) -> Path:
    (empty_core_cache / "0.115.0" / "bin").mkdir()
    (empty_core_cache / "0.115.0" / "bin" / "mktmp.sh").touch()
    return empty_core_cache


@pytest.fixture()
def qa_root(make_plugin_cache: Callable[..., Path]) -> Path:
    root = make_plugin_cache(plugin_name="dev10x-qa", version="0.115.0")
    (root / "skills" / "tts").mkdir(parents=True)
    return root


@pytest.fixture()
def qa_script(qa_root: Path) -> Path:
    scripts = qa_root / "skills" / "tts" / "scripts"
    scripts.mkdir()
    script = scripts / "say.py"
    script.touch()
    return script


class TestEnsureScriptsSeedsSatellites:
    """GH-1807: a skill that moved to a satellite plugin gets its grants too."""

    @pytest.fixture()
    def result(
        self,
        core_cache: Path,
        qa_script: Path,
        settings_file: Path,
        satellite_plugin_map: PluginMap,
    ) -> dict[str, object]:
        return update_paths.ensure_scripts(
            config={"plugin_cache": str(core_cache)},
            settings_files=[settings_file],
            dry_run=False,
            quiet=False,
            plugin_map=satellite_plugin_map,
        )

    @pytest.fixture()
    def allow(
        self,
        result: dict[str, object],
        settings_file: Path,
        read_allow: Callable[[Path], list[str]],
    ) -> list[str]:
        return read_allow(settings_file)

    def test_seeds_satellite_cache_rule(self, allow: list[str], qa_script: Path) -> None:
        assert f"Bash({qa_script}:*)" in allow

    def test_keeps_core_cache_rule(self, allow: list[str], core_cache: Path) -> None:
        assert f"Bash({core_cache}/0.115.0/bin/mktmp.sh:*)" in allow

    def test_seeds_satellite_marketplace_twins_with_plugins_infix(
        self, allow: list[str], fake_home: Path
    ) -> None:
        rel = ".claude/plugins/marketplaces/Dev10x-Guru/plugins/qa/skills/tts/scripts/say.py"
        assert f"Bash(~/{rel}:*)" in allow
        assert f"Bash({fake_home}/{rel}:*)" in allow
        assert not any("marketplaces/Dev10x-Guru/skills/tts/" in rule for rule in allow)

    def test_only_installed_satellite_is_seeded(self, allow: list[str], qa_script: Path) -> None:
        assert f"Bash({qa_script}:*)" in allow
        assert not any("dev10x-infra" in rule or "plugins/infra" in rule for rule in allow)

    def test_reports_every_scanned_root(self, result: dict[str, object], core_cache: Path) -> None:
        joined = "\n".join(result["messages"])
        assert f"Plugin root: {core_cache / '0.115.0'}" in joined
        assert f"Plugin root: {core_cache.parent / 'dev10x-qa' / '0.115.0'}" in joined
        assert "Scripts found: 2" in joined


class TestEnsureScriptsSeedsSatelliteOnly:
    """GH-1807: a satellite's scripts seed even when core itself has none."""

    @pytest.fixture()
    def result(
        self,
        empty_core_cache: Path,
        qa_script: Path,
        settings_file: Path,
        satellite_plugin_map: PluginMap,
    ) -> dict[str, object]:
        return update_paths.ensure_scripts(
            config={"plugin_cache": str(empty_core_cache)},
            settings_files=[settings_file],
            dry_run=False,
            quiet=True,
            plugin_map=satellite_plugin_map,
        )

    def test_writes_the_settings_file(self, result: dict[str, object]) -> None:
        assert result["files_changed"] == 1

    def test_seeds_the_satellite_rule(
        self,
        result: dict[str, object],
        settings_file: Path,
        qa_script: Path,
        read_allow: Callable[[Path], list[str]],
    ) -> None:
        assert f"Bash({qa_script}:*)" in read_allow(settings_file)

    def test_does_not_report_no_scripts(self, result: dict[str, object]) -> None:
        assert not any("No callable scripts" in m for m in result["messages"])


class TestEnsureReadsSeedsSatellites:
    """GH-1807: a satellite's skill folders get versioned Read rules too."""

    @pytest.fixture()
    def allow(
        self,
        empty_core_cache: Path,
        qa_root: Path,
        settings_file: Path,
        satellite_plugin_map: PluginMap,
        read_allow: Callable[[Path], list[str]],
    ) -> list[str]:
        update_paths.ensure_reads(
            config={"plugin_cache": str(empty_core_cache)},
            settings_files=[settings_file],
            dry_run=False,
            quiet=True,
            plugin_map=satellite_plugin_map,
        )
        return read_allow(settings_file)

    def test_seeds_satellite_skill_read_rules(self, allow: list[str], fake_home: Path) -> None:
        rel = ".claude/plugins/cache/Dev10x-Guru/dev10x-qa/0.115.0/skills/tts"
        assert f"Read(~/{rel}/*)" in allow
        assert f"Read({fake_home}/{rel}/*)" in allow

    def test_keeps_core_skill_read_rules(self, allow: list[str], fake_home: Path) -> None:
        rel = ".claude/plugins/cache/Dev10x-Guru/dev10x/0.115.0/skills/ask"
        assert f"Read(~/{rel}/*)" in allow
        assert f"Read({fake_home}/{rel}/*)" in allow

    def test_only_installed_satellite_gets_read_rules(self, allow: list[str]) -> None:
        assert any("dev10x-qa" in rule for rule in allow)
        assert not any("dev10x-infra" in rule for rule in allow)


# ── GH-606 AC2: user-skill script enumeration ───────────────────────────

_VERB_AWARE_WRAPPER = (
    "#!/usr/bin/env bash\n"
    "ALLOWED_VERBS=(get describe)\n"
    'aws-vault exec "$PROFILE" -- kubectl "$VERB" "$@"\n'
)
_VERB_BLIND_WRAPPER = '#!/usr/bin/env bash\naws-vault exec "$PROFILE" -- kubectl "$@"\n'
_PLAIN_SCRIPT = "#!/usr/bin/env bash\necho hello\n"


class TestScanUserSkillScripts:
    @pytest.fixture()
    def skills_root(self, tmp_path: Path) -> Path:
        root = tmp_path / ".claude" / "skills"
        (root / "my:daily-yt" / "scripts").mkdir(parents=True)
        (root / "my:daily-yt" / "scripts" / "run.sh").write_text(_PLAIN_SCRIPT)
        (root / "kb-checkin" / "scripts").mkdir(parents=True)
        (root / "kb-checkin" / "scripts" / "checkin.py").write_text("print(1)\n")
        return root

    def test_finds_sh_and_py(self, skills_root: Path) -> None:
        result = update_paths.scan_user_skill_scripts(skills_root)

        names = [s.name for s in result]
        assert "run.sh" in names
        assert "checkin.py" in names

    def test_handles_colon_kept_personal_dir(self, skills_root: Path) -> None:
        result = update_paths.scan_user_skill_scripts(skills_root)

        assert any("my:daily-yt" in str(s) for s in result)

    def test_returns_sorted_unique(self, skills_root: Path) -> None:
        result = update_paths.scan_user_skill_scripts(skills_root)

        assert result == sorted(set(result))

    def test_returns_empty_when_root_absent(self, tmp_path: Path) -> None:
        assert update_paths.scan_user_skill_scripts(tmp_path / "nope") == []


class TestIsVerbBlindCredentialedWrapper:
    def test_verb_blind_passthrough_is_flagged(self, tmp_path: Path) -> None:
        script = tmp_path / "wrap.sh"
        script.write_text(_VERB_BLIND_WRAPPER)
        assert update_paths.is_verb_blind_credentialed_wrapper(script) is True

    def test_verb_aware_wrapper_is_not_flagged(self, tmp_path: Path) -> None:
        script = tmp_path / "wrap.sh"
        script.write_text(_VERB_AWARE_WRAPPER)
        assert update_paths.is_verb_blind_credentialed_wrapper(script) is False

    def test_non_credentialed_script_is_not_flagged(self, tmp_path: Path) -> None:
        script = tmp_path / "plain.sh"
        script.write_text(_PLAIN_SCRIPT)
        assert update_paths.is_verb_blind_credentialed_wrapper(script) is False

    def test_missing_file_is_not_flagged(self, tmp_path: Path) -> None:
        assert update_paths.is_verb_blind_credentialed_wrapper(tmp_path / "gone.sh") is False


class TestBuildUserSkillScriptRules:
    def test_emits_home_twins(self, tmp_path: Path) -> None:
        skills_root = tmp_path / ".claude" / "skills"
        (skills_root / "kb-checkin" / "scripts").mkdir(parents=True)
        script = skills_root / "kb-checkin" / "scripts" / "checkin.py"
        script.write_text("print(1)\n")

        rules, skipped = update_paths.build_user_skill_script_rules(
            [script], skills_root=skills_root, user_home=tmp_path
        )

        home = tmp_path.resolve()
        assert rules == [
            "Bash(~/.claude/skills/kb-checkin/scripts/checkin.py:*)",
            f"Bash({home}/.claude/skills/kb-checkin/scripts/checkin.py:*)",
        ]
        assert skipped == []

    def test_skips_verb_blind_wrapper(self, tmp_path: Path) -> None:
        skills_root = tmp_path / ".claude" / "skills"
        (skills_root / "aws-vault" / "scripts").mkdir(parents=True)
        blind = skills_root / "aws-vault" / "scripts" / "wrap.sh"
        blind.write_text(_VERB_BLIND_WRAPPER)

        rules, skipped = update_paths.build_user_skill_script_rules(
            [blind], skills_root=skills_root, user_home=tmp_path
        )

        assert rules == []
        assert skipped == [blind]

    def test_colon_kept_dir_in_rule(self, tmp_path: Path) -> None:
        skills_root = tmp_path / ".claude" / "skills"
        (skills_root / "my:daily-yt" / "scripts").mkdir(parents=True)
        script = skills_root / "my:daily-yt" / "scripts" / "run.sh"
        script.write_text(_PLAIN_SCRIPT)

        rules, _skipped = update_paths.build_user_skill_script_rules(
            [script], skills_root=skills_root, user_home=tmp_path
        )

        assert "Bash(~/.claude/skills/my:daily-yt/scripts/run.sh:*)" in rules

    def test_returns_empty_when_root_outside_home(self, tmp_path: Path) -> None:
        outside = tmp_path / "elsewhere" / "skills"
        outside.mkdir(parents=True)
        rules, skipped = update_paths.build_user_skill_script_rules(
            [outside / "x.sh"], skills_root=outside, user_home=tmp_path / "home"
        )

        assert rules == []
        assert skipped == []


class TestEnsureUserSkillScripts:
    @pytest.fixture()
    def skills_root(self, tmp_path: Path) -> Path:
        root = tmp_path / ".claude" / "skills"
        (root / "kb-checkin" / "scripts").mkdir(parents=True)
        (root / "kb-checkin" / "scripts" / "checkin.py").write_text("print(1)\n")
        (root / "aws-vault" / "scripts").mkdir(parents=True)
        (root / "aws-vault" / "scripts" / "wrap.sh").write_text(_VERB_BLIND_WRAPPER)
        return root

    def test_adds_rules_and_skips_verb_blind(
        self,
        tmp_path: Path,
        skills_root: Path,
        read_allow: Callable[[Path], list[str]],
    ) -> None:
        settings = tmp_path / "settings.local.json"
        settings.write_text(json.dumps({"permissions": {"allow": []}}))

        result = update_paths.ensure_user_skill_scripts(
            settings_files=[settings],
            skills_root=skills_root,
            user_home=tmp_path,
            dry_run=False,
            quiet=True,
        )

        allow = read_allow(settings)
        assert "Bash(~/.claude/skills/kb-checkin/scripts/checkin.py:*)" in allow
        assert not any("wrap.sh" in r for r in allow)
        assert result["files_changed"] == 1

    def test_idempotent_second_run(self, tmp_path: Path, skills_root: Path) -> None:
        settings = tmp_path / "settings.local.json"
        settings.write_text(json.dumps({"permissions": {"allow": []}}))
        update_paths.ensure_user_skill_scripts(
            settings_files=[settings],
            skills_root=skills_root,
            user_home=tmp_path,
            dry_run=False,
            quiet=True,
        )
        snapshot = settings.read_text()

        result = update_paths.ensure_user_skill_scripts(
            settings_files=[settings],
            skills_root=skills_root,
            user_home=tmp_path,
            dry_run=False,
            quiet=True,
        )

        assert result["files_changed"] == 0
        assert settings.read_text() == snapshot

    def test_dry_run_does_not_write(self, tmp_path: Path, skills_root: Path) -> None:
        settings = tmp_path / "settings.local.json"
        settings.write_text(json.dumps({"permissions": {"allow": []}}))
        original = settings.read_text()

        update_paths.ensure_user_skill_scripts(
            settings_files=[settings],
            skills_root=skills_root,
            user_home=tmp_path,
            dry_run=True,
            quiet=True,
        )

        assert settings.read_text() == original

    def test_reports_when_no_scripts(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.local.json"
        settings.write_text(json.dumps({"permissions": {"allow": []}}))

        result = update_paths.ensure_user_skill_scripts(
            settings_files=[settings],
            skills_root=tmp_path / "empty",
            user_home=tmp_path,
            dry_run=False,
            quiet=False,
        )

        assert result["exit_code"] == 0
        assert any("No user-skill scripts" in m for m in result["messages"])

    def test_verbose_dry_run_reports_skips_and_would_add(
        self, tmp_path: Path, skills_root: Path
    ) -> None:
        settings = tmp_path / "settings.local.json"
        settings.write_text(json.dumps({"permissions": {"allow": []}}))
        original = settings.read_text()

        result = update_paths.ensure_user_skill_scripts(
            settings_files=[settings],
            skills_root=skills_root,
            user_home=tmp_path,
            dry_run=True,
            quiet=False,
        )

        joined = "\n".join(result["messages"])
        assert "User-skill scripts root:" in joined
        assert "SKIP (verb-blind credentialed wrapper" in joined
        assert "dry run — no files will be modified" in joined
        assert "Would add" in joined
        assert settings.read_text() == original
