"""Tests for the AllowRule value object and AllowRuleLoader.

The ``TestSemanticDivergence`` class pins the cases where the four
pre-consolidation matchers disagreed (audit C2, 2026-05-18). Each test
documents what a now-removed implementation used to return so the unified
behavior is auditable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.domain.common.allow_rule import AllowRule, AllowRuleLoader


class TestParse:
    def test_bash_rule(self) -> None:
        rule = AllowRule.parse("Bash(git status:*)")
        assert rule.tool == "Bash"
        assert rule.pattern == "git status:*"
        assert rule.raw == "Bash(git status:*)"

    def test_path_rule(self) -> None:
        rule = AllowRule.parse("Write(/tmp/Dev10x/**)")
        assert rule.tool == "Write"
        assert rule.pattern == "/tmp/Dev10x/**"

    def test_mcp_rule_has_no_pattern(self) -> None:
        rule = AllowRule.parse("mcp__plugin_Dev10x_cli__*")
        assert rule.tool == "mcp__plugin_Dev10x_cli__*"
        assert rule.pattern == ""
        assert rule.raw == "mcp__plugin_Dev10x_cli__*"

    def test_bare_token_without_parens(self) -> None:
        rule = AllowRule.parse("WebFetch")
        assert rule.tool == "WebFetch"
        assert rule.pattern == ""

    def test_str_returns_raw(self) -> None:
        assert str(AllowRule.parse("Bash(ls:*)")) == "Bash(ls:*)"


class TestFactories:
    @pytest.mark.parametrize(
        ("factory", "arg", "expected"),
        [
            (AllowRule.bash, "find /x:*", "Bash(find /x:*)"),
            (AllowRule.read, "/x/**", "Read(/x/**)"),
            (AllowRule.write, "/x/**", "Write(/x/**)"),
            (AllowRule.edit, "/x/**", "Edit(/x/**)"),
            (AllowRule.skill, "Dev10x:git-commit", "Skill(Dev10x:git-commit)"),
        ],
    )
    def test_factory_builds_rule(self, factory, arg: str, expected: str) -> None:
        rule = factory(arg)
        assert rule.raw == expected
        assert str(rule) == expected


class TestBashMatching:
    def test_prefix_exact(self) -> None:
        assert AllowRule.parse("Bash(git status:*)").matches("Bash(git status)")

    def test_prefix_with_args(self) -> None:
        assert AllowRule.parse("Bash(git push:*)").matches("Bash(git push --force)")

    def test_prefix_token_boundary_rejects_partial(self) -> None:
        # `git` must not match `github-cli` — the space boundary guards it.
        assert not AllowRule.parse("Bash(git:*)").matches("Bash(github-cli auth)")

    def test_different_tool_rejected(self) -> None:
        assert not AllowRule.parse("Bash(npm:*)").matches("Bash(git status)")

    def test_exact_pattern_without_wildcard(self) -> None:
        assert AllowRule.parse("Bash(ls)").matches("Bash(ls)")
        assert not AllowRule.parse("Bash(ls)").matches("Bash(ls -la)")

    def test_tilde_expands_against_home_command(self) -> None:
        home = str(Path.home())
        rule = AllowRule.parse("Bash(~/.claude/skills/foo.sh:*)")
        assert rule.matches(f"Bash({home}/.claude/skills/foo.sh --x)")


class TestPathMatching:
    def test_double_star_directory_prefix(self) -> None:
        rule = AllowRule.parse("Write(/tmp/Dev10x/**)")
        assert rule.matches("Write(/tmp/Dev10x/msg.txt)")
        assert rule.matches("Write(/tmp/Dev10x/git/msg.txt)")

    def test_double_star_rejects_outside_prefix(self) -> None:
        assert not AllowRule.parse("Read(/tmp/Dev10x/**)").matches("Read(/etc/passwd)")

    def test_single_star_glob(self) -> None:
        assert AllowRule.parse("Read(/x/*.py)").matches("Read(/x/mod.py)")

    def test_single_star_crosses_slash_via_fnmatch(self) -> None:
        # Non-``**`` path patterns fall back to fnmatch, whose ``*`` matches
        # ``/`` — the same behavior permission_diagnostics had before
        # consolidation. Documented so the fnmatch fallback is intentional.
        assert AllowRule.parse("Read(/x/*.py)").matches("Read(/x/sub/mod.py)")


class TestMcpMatching:
    def test_wildcard_matches_server_tools(self) -> None:
        rule = AllowRule.parse("mcp__plugin_Dev10x_cli__*")
        assert rule.matches("mcp__plugin_Dev10x_cli__detect_tracker")

    def test_wildcard_rejects_other_server(self) -> None:
        rule = AllowRule.parse("mcp__plugin_Dev10x_cli__*")
        assert not rule.matches("mcp__other_server__tool")

    def test_signature_without_parens_falls_back_to_fnmatch(self) -> None:
        # A non-mcp parenless signature (e.g. "WebFetch()") still resolves.
        assert AllowRule.parse("WebFetch*").matches("WebFetch")

    def test_paren_rule_against_parenless_signature(self) -> None:
        # A ``Tool(pattern)`` rule cannot match a bare signature.
        assert not AllowRule.parse("Bash(git:*)").matches("WebSearch")

    def test_different_tool_with_parens_rejected(self) -> None:
        assert not AllowRule.parse("Read(/x/y)").matches("Write(/x/y)")


class TestSemanticDivergence:
    """Regression fixtures pinning the unified behavior (audit C2)."""

    def test_partial_token_false_positive_now_rejected(self) -> None:
        # prefix_friction / analyze_permissions used loose ``startswith`` and
        # would have matched ``git`` against ``gitfoo``. The unified matcher
        # enforces a space boundary and rejects it.
        assert not AllowRule.parse("Bash(git:*)").matches("Bash(gitfoo)")

    def test_empty_rule_set_does_not_match_everything(self) -> None:
        # analyze_permissions.matches_allow_rule returned ``True`` when the
        # rule list was empty (match-all). The unified matcher leaves that
        # policy to the caller: a single rule only matches its own signature.
        assert not AllowRule.parse("Bash(ls:*)").matches("Bash(rm -rf /)")


class TestLoader:
    def _write(self, tmp_path: Path, payload: dict) -> Path:
        p = tmp_path / "settings.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        return p

    def test_load_returns_rules(self, tmp_path: Path) -> None:
        p = self._write(tmp_path, {"permissions": {"allow": ["Bash(git:*)"]}})
        assert AllowRuleLoader.load(p) == ["Bash(git:*)"]

    def test_load_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert AllowRuleLoader.load(tmp_path / "nope.json") == []

    def test_load_malformed_json_returns_empty(self, tmp_path: Path) -> None:
        p = tmp_path / "settings.json"
        p.write_text("{not json", encoding="utf-8")
        assert AllowRuleLoader.load(p) == []

    def test_load_non_list_allow_returns_empty(self, tmp_path: Path) -> None:
        p = self._write(tmp_path, {"permissions": {"allow": "Bash(git:*)"}})
        assert AllowRuleLoader.load(p) == []

    def test_load_optional_distinguishes_empty_from_absent(self, tmp_path: Path) -> None:
        empty = self._write(tmp_path, {"permissions": {"allow": []}})
        assert AllowRuleLoader.load_optional(empty) == []

        absent = tmp_path / "absent.json"
        absent.write_text(json.dumps({"permissions": {}}), encoding="utf-8")
        assert AllowRuleLoader.load_optional(absent) is None

    def test_load_optional_missing_file_is_none(self, tmp_path: Path) -> None:
        assert AllowRuleLoader.load_optional(tmp_path / "nope.json") is None
