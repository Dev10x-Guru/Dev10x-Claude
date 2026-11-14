"""`clean` detects uppercase-Dev10x Read globs and wrapped direct scripts (GH-1925)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.skills.permission import clean_project_files as clean_mod

UPPERCASE_READS = [
    "Read(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/**)",
    "Read(/home/u/.claude/plugins/cache/Dev10x-Guru/Dev10x/0.68.0/skills/**)",
]
WRAPPED_SCRIPTS = [
    "Bash(/tmp/Dev10x/bin/mktmp.sh:*)",
    "Bash(/home/u/.claude/plugins/cache/Dev10x-Guru/dev10x/0.9.0/skills/git/scripts/"
    "git-push-safe.sh:*)",
    "Bash(${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-create/scripts/create-pr.sh origin)",
]


class TestIsUppercasePluginReadGlob:
    @pytest.mark.parametrize("rule", UPPERCASE_READS)
    def test_detects_uppercase_plugin_directory_globs(self, rule: str) -> None:
        assert clean_mod.is_uppercase_plugin_read_glob(rule) is True

    @pytest.mark.parametrize(
        "rule",
        [
            "Read(~/.claude/plugins/cache/Dev10x-Guru/dev10x/**)",
            "Read(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/0.68.0/skills/git/SKILL.md)",
            "Read(~/.claude/skills/Dev10x:upgrade-cleanup/**)",
            "Read(~/.config/Dev10x/**)",
            "Bash(git log:*)",
        ],
    )
    def test_rejects_live_or_unglobbed_rules(self, rule: str) -> None:
        assert clean_mod.is_uppercase_plugin_read_glob(rule) is False


class TestIsWrappedScriptRule:
    @pytest.mark.parametrize("rule", WRAPPED_SCRIPTS)
    def test_detects_scripts_a_tool_wraps(self, rule: str) -> None:
        assert clean_mod.is_wrapped_script_rule(rule) is True

    @pytest.mark.parametrize(
        "rule",
        [
            "Bash(git log:*)",
            "Bash(/home/u/.claude/skills/other/scripts/unrelated.sh:*)",
            "Read(/tmp/Dev10x/bin/mktmp.sh)",
            "Bash(/tmp/Dev10x/bin/mktmp.sh.bak:*)",
        ],
    )
    def test_rejects_unwrapped_scripts_and_other_tools(self, rule: str) -> None:
        assert clean_mod.is_wrapped_script_rule(rule) is False


class TestClassifyStaleClasses:
    @pytest.fixture
    def result(self) -> clean_mod.RemovalResult:
        return clean_mod.classify_rules(
            [*UPPERCASE_READS, *WRAPPED_SCRIPTS, "Bash(git log:*)"],
            global_rules=set(),
            current_version=None,
        )

    def test_reports_uppercase_reads_under_their_own_category(
        self, result: clean_mod.RemovalResult
    ) -> None:
        assert result.uppercase_plugin_reads == UPPERCASE_READS

    def test_reports_wrapped_scripts_under_their_own_category(
        self, result: clean_mod.RemovalResult
    ) -> None:
        assert result.wrapped_scripts == WRAPPED_SCRIPTS

    def test_counts_both_as_removed_and_keeps_the_rest(
        self, result: clean_mod.RemovalResult
    ) -> None:
        assert (result.total_removed, result.kept) == (5, ["Bash(git log:*)"])

    def test_keeps_a_catalogued_wrapped_script(self) -> None:
        result = clean_mod.classify_rules(
            WRAPPED_SCRIPTS[:1],
            global_rules=set(),
            current_version=None,
            base_permissions=set(WRAPPED_SCRIPTS[:1]),
        )

        assert result.wrapped_scripts == []


class TestCleanFileReportsStaleClasses:
    @pytest.fixture
    def settings(self, tmp_path: Path) -> Path:
        path = tmp_path / "settings.local.json"
        path.write_text(
            json.dumps(
                {"permissions": {"allow": [*UPPERCASE_READS, *WRAPPED_SCRIPTS, "Bash(git log:*)"]}}
            )
        )
        return path

    @pytest.fixture
    def dry_run_messages(self, settings: Path) -> list[str]:
        _, messages = clean_mod.clean_file(
            settings,
            global_rules=set(),
            current_version=None,
            dry_run=True,
            verbose=True,
        )
        return messages

    def test_lists_each_class_under_its_own_heading(self, dry_run_messages: list[str]) -> None:
        headings = [line for line in dry_run_messages if line.startswith("  - ")]
        assert headings == [
            "  - 2 Read globs on the pre-rename uppercase Dev10x/ plugin directory",
            "  - 3 direct-script rules for scripts a skill or MCP tool now wraps",
        ]

    def test_names_every_rule_when_verbose(self, dry_run_messages: list[str]) -> None:
        listed = [line.strip() for line in dry_run_messages if line.startswith("    ")]
        assert listed == [*UPPERCASE_READS, *WRAPPED_SCRIPTS]

    def test_dry_run_leaves_the_file_alone(
        self, settings: Path, dry_run_messages: list[str]
    ) -> None:
        allow = json.loads(settings.read_text())["permissions"]["allow"]
        assert len(allow) == 6

    def test_a_real_run_prunes_both_classes(self, settings: Path) -> None:
        clean_mod.clean_file(settings, global_rules=set(), current_version=None)

        allow = json.loads(settings.read_text())["permissions"]["allow"]
        assert allow == ["Bash(git log:*)"]

    def test_quiet_when_not_verbose(self, settings: Path) -> None:
        _, messages = clean_mod.clean_file(
            settings, global_rules=set(), current_version=None, dry_run=True
        )

        assert not [line for line in messages if line.startswith("    ")]
