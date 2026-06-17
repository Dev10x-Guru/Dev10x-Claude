"""Schema validation tests for command-skill-map.yaml.

Asserts that every rule entry contains the required fields and that
every hook-block rule has at least one compensation entry.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

_YAML_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "src"
    / "dev10x"
    / "validators"
    / "command-skill-map.yaml"
)

_REQUIRED_RULE_FIELDS: frozenset[str] = frozenset(
    {"name", "hook_block", "compensations", "reason"}
)


def _load_rules() -> list[dict[str, Any]]:
    data: dict[str, Any] = yaml.safe_load(_YAML_PATH.read_text()) or {}
    return data.get("rules", [])


def _hook_block_rules() -> list[dict[str, Any]]:
    return [r for r in _load_rules() if r.get("hook_block") is True]


def _all_rule_ids() -> list[str]:
    return [r.get("name", f"<unnamed-{i}>") for i, r in enumerate(_load_rules())]


def _hook_block_rule_ids() -> list[str]:
    return [r.get("name", f"<unnamed-{i}>") for i, r in enumerate(_hook_block_rules())]


class TestYamlFileAccessible:
    def test_yaml_file_exists(self) -> None:
        assert _YAML_PATH.exists(), f"YAML not found at {_YAML_PATH}"

    def test_yaml_parses_without_error(self) -> None:
        data = yaml.safe_load(_YAML_PATH.read_text())
        assert isinstance(data, dict)

    def test_rules_list_is_non_empty(self) -> None:
        rules = _load_rules()
        assert len(rules) > 0


class TestRequiredFields:
    @pytest.mark.parametrize("rule_name", _all_rule_ids())
    def test_rule_has_name(self, rule_name: str) -> None:
        rules = {r.get("name", f"<unnamed-{i}>"): r for i, r in enumerate(_load_rules())}
        rule = rules[rule_name]
        assert "name" in rule, f"Rule {rule_name!r} is missing 'name'"

    @pytest.mark.parametrize("rule_name", _all_rule_ids())
    def test_rule_has_hook_block(self, rule_name: str) -> None:
        rules = {r.get("name", f"<unnamed-{i}>"): r for i, r in enumerate(_load_rules())}
        rule = rules[rule_name]
        assert "hook_block" in rule, f"Rule {rule_name!r} is missing 'hook_block'"

    @pytest.mark.parametrize("rule_name", _all_rule_ids())
    def test_rule_has_compensations(self, rule_name: str) -> None:
        rules = {r.get("name", f"<unnamed-{i}>"): r for i, r in enumerate(_load_rules())}
        rule = rules[rule_name]
        assert "compensations" in rule, f"Rule {rule_name!r} is missing 'compensations'"

    @pytest.mark.parametrize("rule_name", _all_rule_ids())
    def test_rule_has_reason(self, rule_name: str) -> None:
        rules = {r.get("name", f"<unnamed-{i}>"): r for i, r in enumerate(_load_rules())}
        rule = rules[rule_name]
        assert "reason" in rule, f"Rule {rule_name!r} is missing 'reason'"


class TestHookBlockCompensations:
    @pytest.mark.parametrize("rule_name", _hook_block_rule_ids())
    def test_hook_block_rule_has_non_empty_compensations(self, rule_name: str) -> None:
        rules = {r.get("name", f"<unnamed-{i}>"): r for i, r in enumerate(_hook_block_rules())}
        rule = rules[rule_name]
        compensations = rule.get("compensations", [])
        assert isinstance(compensations, list), (
            f"Rule {rule_name!r} 'compensations' must be a list"
        )
        assert len(compensations) > 0, (
            f"Hook-block rule {rule_name!r} must have at least one compensation"
        )

    @pytest.mark.parametrize("rule_name", _hook_block_rule_ids())
    def test_hook_block_compensation_has_type(self, rule_name: str) -> None:
        rules = {r.get("name", f"<unnamed-{i}>"): r for i, r in enumerate(_hook_block_rules())}
        rule = rules[rule_name]
        for idx, comp in enumerate(rule.get("compensations", [])):
            assert "type" in comp, f"Rule {rule_name!r} compensation[{idx}] is missing 'type'"


def _rule_by_name(name: str) -> dict[str, Any]:
    for rule in _load_rules():
        if rule.get("name") == name:
            return rule
    raise AssertionError(f"Rule {name!r} not found in command-skill-map.yaml")


def _matches_any_pattern(*, rule: dict[str, Any], command: str) -> bool:
    return any(re.search(pattern, command) for pattern in rule.get("patterns", []))


def _compensation_targets(rule: dict[str, Any]) -> set[str]:
    targets: set[str] = set()
    for comp in rule.get("compensations", []):
        targets.update(str(comp[field]) for field in ("tool", "skill") if field in comp)
    return targets


class TestGh609RoutingEntries:
    """Each net-new raw shape (GH-609) is recognized and routes to a wrapper/tool."""

    def test_handrolled_ci_loop_recognized(self) -> None:
        rule = _rule_by_name("ci-loop-handrolled")
        assert _matches_any_pattern(
            rule=rule, command="while true; do gh pr checks; sleep 10; done"
        )

    def test_handrolled_ci_loop_routes_to_ci_check_status(self) -> None:
        rule = _rule_by_name("ci-loop-handrolled")
        assert "mcp__plugin_Dev10x_cli__ci_check_status" in _compensation_targets(rule)
        assert "Dev10x:gh-pr-monitor" in _compensation_targets(rule)

    def test_cat_grep_pipeline_recognized(self) -> None:
        rule = _rule_by_name("cat-grep-pipeline")
        assert _matches_any_pattern(rule=rule, command="cat notes.txt | grep TODO")

    def test_grep_brace_expansion_recognized(self) -> None:
        rule = _rule_by_name("cat-grep-pipeline")
        assert _matches_any_pattern(rule=rule, command="grep -n foo src/app.{py,md}")

    def test_cat_grep_routes_to_grep_tool(self) -> None:
        rule = _rule_by_name("cat-grep-pipeline")
        assert "Grep" in _compensation_targets(rule)

    def test_fish_interactive_abbr_recognized(self) -> None:
        rule = _rule_by_name("fish-interactive-abbr")
        assert _matches_any_pattern(rule=rule, command="fish -ic gco")

    def test_version_pinned_plugin_script_recognized(self) -> None:
        rule = _rule_by_name("version-pinned-plugin-script")
        cmd = "/home/u/.claude/plugins/cache/Dev10x/0.79.0/skills/x/scripts/y.py"
        assert _matches_any_pattern(rule=rule, command=cmd)

    @pytest.mark.parametrize(
        "name",
        [
            "ci-loop-handrolled",
            "cat-grep-pipeline",
            "fish-interactive-abbr",
            "version-pinned-plugin-script",
        ],
    )
    def test_new_entries_are_advisory(self, name: str) -> None:
        # These are diag-friction routing hints, not enforced hook blocks.
        assert _rule_by_name(name)["hook_block"] is False

    @pytest.mark.parametrize(
        "name",
        [
            "ci-loop-handrolled",
            "cat-grep-pipeline",
            "fish-interactive-abbr",
            "version-pinned-plugin-script",
        ],
    )
    def test_new_entry_patterns_compile(self, name: str) -> None:
        for pattern in _rule_by_name(name)["patterns"]:
            re.compile(pattern)

    def test_graphql_variants_already_routed(self) -> None:
        # GH-609 also lists the 3 gh api graphql variants; GH-598 already
        # covers them via gh-review-threads-graphql → unresolved_threads.
        rule = _rule_by_name("gh-review-threads-graphql")
        assert "mcp__plugin_Dev10x_cli__unresolved_threads" in _compensation_targets(rule)
