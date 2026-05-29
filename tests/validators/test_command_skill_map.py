"""Schema validation tests for command-skill-map.yaml.

Asserts that every rule entry contains the required fields and that
every hook-block rule has at least one compensation entry.
"""

from __future__ import annotations

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
