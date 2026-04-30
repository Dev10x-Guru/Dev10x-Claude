"""Tests for the ensure-reads action (GH-48).

Covers the per-skill Read rule emitter that ships ~/ and /home/<user>/
twin variants. Tests use throwaway fixture trees so they do not depend
on the real plugin cache layout.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.skills.permission.update_paths import (
    READ_TOP_LEVEL_DIRS,
    build_read_allow_rules,
    ensure_read_rules,
    scan_skill_directories,
    scan_top_level_dirs,
    verify_read_coverage,
)


@pytest.fixture
def fake_home(tmp_path: Path) -> Path:
    """Materialize a HOME-like directory and return its path."""
    home = tmp_path / "home" / "tester"
    home.mkdir(parents=True)
    return home


@pytest.fixture
def fake_plugin_root(fake_home: Path) -> Path:
    """Materialize a plugin cache layout under fake_home.

    Mirrors the real shape:
      <home>/.claude/plugins/cache/<publisher>/<plugin>/<version>/
        skills/<name>/
        agents/
        commands/
        hooks/scripts/
        bin/
        ...
    """
    plugin_root = (
        fake_home / ".claude" / "plugins" / "cache" / "Dev10x-Guru" / "Dev10x" / "9.9.9"
    )
    skills_dir = plugin_root / "skills"
    for skill in ["alpha-skill", "beta-skill"]:
        (skills_dir / skill).mkdir(parents=True)
        (skills_dir / skill / "SKILL.md").write_text("# " + skill)

    for top in ["agents", "commands", "hooks/scripts", "bin"]:
        target = plugin_root / top
        target.mkdir(parents=True, exist_ok=True)
        (target / "marker").write_text("present")

    return plugin_root


class TestScanSkillDirectories:
    def test_returns_skill_names_in_sorted_order(self, fake_plugin_root: Path) -> None:
        result = scan_skill_directories(fake_plugin_root)

        assert result == ["alpha-skill", "beta-skill"]

    def test_returns_empty_list_when_skills_dir_missing(self, tmp_path: Path) -> None:
        empty_root = tmp_path / "empty"
        empty_root.mkdir()

        assert scan_skill_directories(empty_root) == []

    def test_ignores_files_only_returns_directories(
        self, fake_plugin_root: Path
    ) -> None:
        (fake_plugin_root / "skills" / "stray-file.txt").write_text("not a skill")

        result = scan_skill_directories(fake_plugin_root)

        assert "stray-file.txt" not in result


class TestScanTopLevelDirs:
    def test_returns_only_existing_dirs(self, fake_plugin_root: Path) -> None:
        result = scan_top_level_dirs(fake_plugin_root)

        for present in ["agents", "commands", "hooks/scripts", "bin"]:
            assert present in result
        for absent in ["servers", "lib", "references", "hooks"]:
            # `hooks` exists implicitly because hooks/scripts was created
            if absent == "hooks":
                assert absent in result
                continue
            assert absent not in result

    def test_returns_subset_of_known_dirs(self, fake_plugin_root: Path) -> None:
        result = scan_top_level_dirs(fake_plugin_root)

        assert set(result).issubset(set(READ_TOP_LEVEL_DIRS))


class TestBuildReadAllowRules:
    def test_emits_twin_variants_for_each_skill(
        self,
        fake_plugin_root: Path,
        fake_home: Path,
    ) -> None:
        rules = build_read_allow_rules(
            plugin_root=fake_plugin_root,
            user_home=fake_home,
        )

        rules_set = set(rules)
        suffix = "Dev10x-Guru/Dev10x/9.9.9/skills/alpha-skill/*"
        assert f"Read(~/.claude/plugins/cache/{suffix})" in rules_set
        assert f"Read({fake_home}/.claude/plugins/cache/{suffix})" in rules_set

    def test_emits_twin_variants_for_version_root(
        self,
        fake_plugin_root: Path,
        fake_home: Path,
    ) -> None:
        rules = build_read_allow_rules(
            plugin_root=fake_plugin_root,
            user_home=fake_home,
        )

        version_rel = "Dev10x-Guru/Dev10x/9.9.9"
        rules_set = set(rules)
        assert f"Read(~/.claude/plugins/cache/{version_rel}/*)" in rules_set
        assert f"Read({fake_home}/.claude/plugins/cache/{version_rel}/*)" in rules_set

    def test_emits_rules_for_all_present_top_level_dirs(
        self,
        fake_plugin_root: Path,
        fake_home: Path,
    ) -> None:
        rules = build_read_allow_rules(
            plugin_root=fake_plugin_root,
            user_home=fake_home,
        )

        for top in scan_top_level_dirs(fake_plugin_root):
            tilde = f"Read(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/9.9.9/{top}/*)"
            assert tilde in rules

    def test_returns_empty_when_plugin_root_outside_home(
        self,
        tmp_path: Path,
        fake_home: Path,
    ) -> None:
        outside = tmp_path / "other-place" / "Dev10x" / "1.0.0"
        outside.mkdir(parents=True)

        rules = build_read_allow_rules(
            plugin_root=outside,
            user_home=fake_home,
        )

        assert rules == []

    def test_uses_single_star_wildcard_only(
        self,
        fake_plugin_root: Path,
        fake_home: Path,
    ) -> None:
        rules = build_read_allow_rules(
            plugin_root=fake_plugin_root,
            user_home=fake_home,
        )

        for rule in rules:
            assert "/**" not in rule, f"Rule uses unsupported '**' glob: {rule}"
            assert "*/**" not in rule


class TestVerifyReadCoverage:
    def test_splits_rules_into_covered_and_missing(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        settings.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "Read(~/.claude/plugins/cache/X/Dev10x/1.0/skills/a/*)",
                            "Bash(unrelated)",
                        ]
                    }
                }
            )
        )

        expected = [
            "Read(~/.claude/plugins/cache/X/Dev10x/1.0/skills/a/*)",
            "Read(~/.claude/plugins/cache/X/Dev10x/1.0/skills/b/*)",
        ]

        covered, missing = verify_read_coverage(settings, expected)

        assert covered == ["Read(~/.claude/plugins/cache/X/Dev10x/1.0/skills/a/*)"]
        assert missing == ["Read(~/.claude/plugins/cache/X/Dev10x/1.0/skills/b/*)"]

    def test_treats_invalid_json_as_missing_everything(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        settings.write_text("{ not valid json")

        covered, missing = verify_read_coverage(settings, ["Read(foo)"])

        assert covered == []
        assert missing == ["Read(foo)"]


class TestEnsureReadRules:
    def test_appends_missing_rules_idempotently(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"permissions": {"allow": ["Read(existing)"]}}))

        ensure_read_rules(
            settings,
            ["Read(new-1)", "Read(new-2)"],
            dry_run=False,
        )
        # Second call should not duplicate.
        ensure_read_rules(
            settings,
            ["Read(new-1)", "Read(new-2)"],
            dry_run=False,
        )

        data = json.loads(settings.read_text())
        allow = data["permissions"]["allow"]
        assert allow.count("Read(new-1)") == 1
        assert allow.count("Read(new-2)") == 1
        assert "Read(existing)" in allow

    def test_dry_run_does_not_modify_file(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"permissions": {"allow": []}}))

        count, messages = ensure_read_rules(
            settings,
            ["Read(would-add)"],
            dry_run=True,
        )

        assert count == 1
        assert any("Read(would-add)" in m for m in messages)
        data = json.loads(settings.read_text())
        assert data["permissions"]["allow"] == []

    def test_returns_zero_when_nothing_missing(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"permissions": {"allow": []}}))

        count, messages = ensure_read_rules(settings, [], dry_run=False)

        assert count == 0
        assert messages == []
