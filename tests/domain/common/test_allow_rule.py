from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.domain.common.allow_rule import AllowRule, AllowRuleLoader


class TestParse:
    def test_parses_tool_and_pattern(self) -> None:
        rule = AllowRule.parse("Bash(git status:*)")

        assert rule.tool == "Bash"
        assert rule.pattern == "git status:*"
        assert rule.raw == "Bash(git status:*)"

    def test_parses_pattern_containing_parens(self) -> None:
        rule = AllowRule.parse("Bash(git log --format=%H)")

        assert rule.tool == "Bash"
        assert rule.pattern == "git log --format=%H"

    def test_bare_tool_has_empty_pattern(self) -> None:
        rule = AllowRule.parse("Read")

        assert rule.tool == "Read"
        assert rule.pattern == ""

    def test_mcp_tool_parses_as_bare(self) -> None:
        rule = AllowRule.parse("mcp__plugin_Dev10x_cli__mktmp")

        assert rule.tool == "mcp__plugin_Dev10x_cli__mktmp"
        assert rule.pattern == ""


class TestTryParse:
    @pytest.mark.parametrize("raw", ["", "   ", None])
    def test_returns_none_for_blank(self, raw: object) -> None:
        assert AllowRule.try_parse(raw) is None  # type: ignore[arg-type]

    def test_returns_rule_for_valid(self) -> None:
        rule = AllowRule.try_parse("Bash(ls:*)")

        assert rule is not None
        assert rule.tool == "Bash"


class TestMatches:
    @pytest.mark.parametrize(
        "rule,signature,expected",
        [
            # `:*` prefix expansion — exact match
            ("Bash(git status:*)", "Bash(git status)", True),
            # `:*` prefix expansion — space-boundary match
            ("Bash(git push:*)", "Bash(git push --force)", True),
            # divergence fixture: bare `startswith` would WRONGLY match a
            # different command sharing the prefix; canonical requires a
            # space (or exact) boundary so `git pushy` is NOT covered.
            ("Bash(git push:*)", "Bash(git pushy)", False),
            ("Bash(git:*)", "Bash(github)", False),
            ("Bash(git:*)", "Bash(git log)", True),
            # tool mismatch never matches
            ("Bash(git:*)", "Read(/etc/hosts)", False),
            # plain fnmatch pattern (no `:*`)
            ("Bash(npm test)", "Bash(npm test)", True),
            ("Bash(npm *)", "Bash(npm test)", True),
            # path tools — `**` recursive prefix
            ("Read(/work/**)", "Read(/work/foo/bar.py)", True),
            ("Read(/work/**)", "Read(/other/bar.py)", False),
            # MCP rules match by fnmatch over the whole signature
            ("mcp__plugin_Dev10x_cli__*", "mcp__plugin_Dev10x_cli__mktmp", True),
            ("mcp__plugin_Dev10x_db__*", "mcp__plugin_Dev10x_cli__mktmp", False),
            # paren-less rules are fnmatch globs over the whole signature
            ("Bash*", "Bash(git status)", True),
            ("Read*", "Bash(git status)", False),
        ],
    )
    def test_matches(self, rule: str, signature: str, expected: bool) -> None:
        assert AllowRule.parse(rule).matches(signature) is expected

    def test_bare_tool_is_literal_not_match_all(self) -> None:
        # A bare ``Read`` rule is a literal fnmatch (impl #1 semantics),
        # so it does NOT cover a parameterised ``Read(...)`` signature.
        assert AllowRule.parse("Read").matches("Read(/etc/hosts)") is False


class TestProperties:
    def test_is_prefix_true_for_star_colon(self) -> None:
        assert AllowRule.parse("Bash(git:*)").is_prefix is True

    def test_is_prefix_false_for_plain(self) -> None:
        assert AllowRule.parse("Bash(git log)").is_prefix is False

    def test_inner_path_strips_colon_suffix(self) -> None:
        assert AllowRule.parse("Bash(~/.claude/tools/foo:*)").inner_path == "~/.claude/tools/foo"

    def test_inner_path_without_colon(self) -> None:
        assert AllowRule.parse("Read(/work/src)").inner_path == "/work/src"


class TestCoversPath:
    def test_covers_exact_prefix(self) -> None:
        assert AllowRule.bash("/work/dx/bin/run").covers_path("/work/dx/bin/run --all") is True

    def test_expands_tilde(self) -> None:
        rule = AllowRule.bash("~/.claude/tools/x")
        home_path = str(Path("~/.claude/tools/x/go").expanduser())

        assert rule.covers_path(home_path) is True

    def test_does_not_cover_unrelated(self) -> None:
        assert AllowRule.bash("/work/dx/bin").covers_path("/other/path") is False

    def test_empty_inner_path_covers_nothing(self) -> None:
        assert AllowRule.parse("Bash").covers_path("anything") is False


class TestFactories:
    @pytest.mark.parametrize(
        "factory,tool,raw",
        [
            (AllowRule.bash, "Bash", "Bash(git:*)"),
            (AllowRule.read, "Read", "Read(git:*)"),
            (AllowRule.skill, "Skill", "Skill(git:*)"),
        ],
    )
    def test_factory_builds_rule(self, factory, tool: str, raw: str) -> None:
        rule = factory("git:*")

        assert rule.tool == tool
        assert rule.pattern == "git:*"
        assert rule.raw == raw


class TestAllowRuleLoader:
    def test_load_returns_allow_strings(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        settings.write_text(
            json.dumps({"permissions": {"allow": ["Bash(git:*)", "Read(/work/**)"]}})
        )

        assert AllowRuleLoader.load(settings) == ["Bash(git:*)", "Read(/work/**)"]

    def test_load_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert AllowRuleLoader.load(tmp_path / "absent.json") == []

    def test_load_malformed_json_returns_empty(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        settings.write_text("{not json")

        assert AllowRuleLoader.load(settings) == []

    def test_load_non_list_allow_returns_empty(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"permissions": {"allow": "Bash(git:*)"}}))

        assert AllowRuleLoader.load(settings) == []

    def test_load_coerces_non_string_entries(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"permissions": {"allow": [123]}}))

        assert AllowRuleLoader.load(settings) == ["123"]

    def test_rules_parses_each_entry(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"permissions": {"allow": ["Bash(git:*)", ""]}}))

        rules = AllowRuleLoader.rules(settings)

        assert [rule.tool for rule in rules] == ["Bash"]
        assert rules[0].pattern == "git:*"
