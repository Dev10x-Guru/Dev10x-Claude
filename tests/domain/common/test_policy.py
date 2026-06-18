"""Tests for the Policy value object and PolicyCatalog (GH-271).

These tests are the executable spec for the structured permission-policy
model that replaces the flat ``base_permissions`` list. A Policy wraps an
:class:`AllowRule` with the three dimensions GH-271 evidence converged on:
``tier`` (audience breadth), ``source`` (who authored the rule), and
``effect`` (Cedar-style allow/ask/deny). ``PolicyCatalog`` parses the
existing grouped ``baseline-permissions.yaml`` into these objects so the
rest of the GH-271 pipeline (deny catalog, source precedence, worktree
sync, doctor drift) has a typed model to build on.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dev10x.domain.common.allow_rule import AllowRule
from dev10x.domain.common.policy import (
    Policy,
    PolicyCatalog,
    PolicyEffect,
    PolicySensitivity,
    PolicySource,
)


class TestPolicyEffect:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("allow", PolicyEffect.ALLOW),
            ("ask", PolicyEffect.ASK),
            ("deny", PolicyEffect.DENY),
            ("ALLOW", PolicyEffect.ALLOW),
            ("  Deny  ", PolicyEffect.DENY),
        ],
    )
    def test_from_yaml_parses_known_values(self, raw: str, expected: PolicyEffect) -> None:
        assert PolicyEffect.from_yaml(raw) == expected

    @pytest.mark.parametrize("raw", ["", "   ", "permit", None, 7, ["allow"]])
    def test_from_yaml_falls_back_to_default(self, raw: object) -> None:
        assert PolicyEffect.from_yaml(raw) == PolicyEffect.default()

    def test_default_is_allow(self) -> None:
        # The baseline catalog is an allow catalog; ALLOW is the safe default.
        assert PolicyEffect.default() == PolicyEffect.ALLOW

    def test_str_value_round_trips(self) -> None:
        assert PolicyEffect.DENY.value == "deny"


class TestPolicySource:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("plugin-default", PolicySource.PLUGIN_DEFAULT),
            ("user-private", PolicySource.USER_PRIVATE),
            ("project-local", PolicySource.PROJECT_LOCAL),
            ("PROJECT-LOCAL", PolicySource.PROJECT_LOCAL),
            ("  user-private ", PolicySource.USER_PRIVATE),
        ],
    )
    def test_from_yaml_parses_known_values(self, raw: str, expected: PolicySource) -> None:
        assert PolicySource.from_yaml(raw) == expected

    @pytest.mark.parametrize("raw", ["", "team", None, 3, {"source": "x"}])
    def test_from_yaml_falls_back_to_default(self, raw: object) -> None:
        assert PolicySource.from_yaml(raw) == PolicySource.default()

    def test_default_is_plugin_default(self) -> None:
        assert PolicySource.default() == PolicySource.PLUGIN_DEFAULT

    def test_str_value_round_trips(self) -> None:
        assert PolicySource.PLUGIN_DEFAULT.value == "plugin-default"


class TestPolicySensitivity:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("benign", PolicySensitivity.BENIGN),
            ("pii", PolicySensitivity.PII),
            ("secret", PolicySensitivity.SECRET),
            ("BENIGN", PolicySensitivity.BENIGN),
            ("  Secret  ", PolicySensitivity.SECRET),
        ],
    )
    def test_from_yaml_parses_known_values(self, raw: str, expected: PolicySensitivity) -> None:
        assert PolicySensitivity.from_yaml(raw) == expected

    @pytest.mark.parametrize("raw", ["", "  ", "private", None, 5, ["benign"]])
    def test_from_yaml_falls_back_to_default(self, raw: object) -> None:
        assert PolicySensitivity.from_yaml(raw) == PolicySensitivity.default()

    def test_default_is_unspecified(self) -> None:
        # A missing sensitivity tag must NOT read as benign — untagged groups
        # are excluded from the proactive-seed surface.
        assert PolicySensitivity.default() == PolicySensitivity.UNSPECIFIED

    def test_str_value_round_trips(self) -> None:
        assert PolicySensitivity.PII.value == "pii"


class TestPolicy:
    def test_from_rule_str_parses_allow_rule(self) -> None:
        policy = Policy.from_rule_str(
            "Bash(git status:*)",
            tier=1,
            source=PolicySource.PLUGIN_DEFAULT,
            group="git-core",
        )
        assert policy.rule == AllowRule.parse("Bash(git status:*)")
        assert policy.tier == 1
        assert policy.source == PolicySource.PLUGIN_DEFAULT
        assert policy.group == "git-core"

    def test_effect_defaults_to_allow(self) -> None:
        policy = Policy.from_rule_str("Bash(ls:*)", tier=1, source=PolicySource.PLUGIN_DEFAULT)
        assert policy.effect == PolicyEffect.ALLOW

    def test_group_defaults_to_empty(self) -> None:
        policy = Policy.from_rule_str("Bash(ls:*)", tier=1, source=PolicySource.PLUGIN_DEFAULT)
        assert policy.group == ""

    def test_sensitivity_defaults_to_unspecified(self) -> None:
        policy = Policy.from_rule_str("Bash(ls:*)", tier=1, source=PolicySource.PLUGIN_DEFAULT)
        assert policy.sensitivity == PolicySensitivity.UNSPECIFIED

    def test_explicit_sensitivity_is_preserved(self) -> None:
        policy = Policy.from_rule_str(
            "mcp__claude_ai_Sentry__search_issues",
            tier=2,
            source=PolicySource.PLUGIN_DEFAULT,
            sensitivity=PolicySensitivity.BENIGN,
        )
        assert policy.sensitivity == PolicySensitivity.BENIGN

    def test_explicit_effect_is_preserved(self) -> None:
        policy = Policy.from_rule_str(
            "Bash(sudo:*)",
            tier=3,
            source=PolicySource.PROJECT_LOCAL,
            effect=PolicyEffect.DENY,
        )
        assert policy.effect == PolicyEffect.DENY

    def test_signature_returns_raw_rule(self) -> None:
        policy = Policy.from_rule_str(
            "Bash(git push:*)", tier=1, source=PolicySource.PLUGIN_DEFAULT
        )
        assert policy.signature == "Bash(git push:*)"

    def test_matches_delegates_to_allow_rule(self) -> None:
        policy = Policy.from_rule_str(
            "Bash(git push:*)", tier=1, source=PolicySource.PLUGIN_DEFAULT
        )
        assert policy.matches("Bash(git push --force)")
        assert not policy.matches("Bash(github-cli auth)")

    def test_is_frozen(self) -> None:
        policy = Policy.from_rule_str("Bash(ls:*)", tier=1, source=PolicySource.PLUGIN_DEFAULT)
        with pytest.raises(AttributeError):
            policy.tier = 2  # type: ignore[misc]


_BASELINE = {
    "version": 1,
    "groups": {
        "git-core": {
            "tier": 1,
            "description": "git porcelain",
            "rules": ["Bash(git status:*)", "Bash(git commit:*)"],
        },
        "docker": {
            "tier": 2,
            "rules": ["Bash(docker ps:*)"],
        },
        "danger": {
            "tier": 3,
            "effect": "deny",
            "rules": ["Bash(sudo:*)"],
        },
    },
}


class TestPolicyCatalogFromDict:
    def test_flattens_groups_into_policies(self) -> None:
        policies = PolicyCatalog.from_baseline_dict(_BASELINE)
        assert [p.signature for p in policies] == [
            "Bash(git status:*)",
            "Bash(git commit:*)",
            "Bash(docker ps:*)",
            "Bash(sudo:*)",
        ]

    def test_carries_group_tier_and_name(self) -> None:
        policies = PolicyCatalog.from_baseline_dict(_BASELINE)
        docker = next(p for p in policies if p.group == "docker")
        assert docker.tier == 2
        assert docker.signature == "Bash(docker ps:*)"

    def test_defaults_effect_to_allow(self) -> None:
        policies = PolicyCatalog.from_baseline_dict(_BASELINE)
        git = next(p for p in policies if p.group == "git-core")
        assert git.effect == PolicyEffect.ALLOW

    def test_group_level_effect_applies_to_all_rules(self) -> None:
        policies = PolicyCatalog.from_baseline_dict(_BASELINE)
        danger = next(p for p in policies if p.group == "danger")
        assert danger.effect == PolicyEffect.DENY

    def test_missing_sensitivity_defaults_to_unspecified(self) -> None:
        policies = PolicyCatalog.from_baseline_dict(_BASELINE)
        assert all(p.sensitivity == PolicySensitivity.UNSPECIFIED for p in policies)

    def test_group_level_sensitivity_applies_to_all_rules(self) -> None:
        data = {
            "groups": {
                "mcp-readonly": {
                    "tier": 2,
                    "sensitivity": "benign",
                    "rules": ["mcp__claude_ai_Acme__search", "mcp__claude_ai_Acme__get"],
                },
            }
        }
        policies = PolicyCatalog.from_baseline_dict(data)
        assert all(p.sensitivity == PolicySensitivity.BENIGN for p in policies)

    def test_source_defaults_to_plugin_default(self) -> None:
        policies = PolicyCatalog.from_baseline_dict(_BASELINE)
        assert all(p.source == PolicySource.PLUGIN_DEFAULT for p in policies)

    def test_source_override_is_applied(self) -> None:
        policies = PolicyCatalog.from_baseline_dict(_BASELINE, source=PolicySource.USER_PRIVATE)
        assert all(p.source == PolicySource.USER_PRIVATE for p in policies)

    def test_missing_tier_defaults_to_zero(self) -> None:
        data = {"groups": {"misc": {"rules": ["Bash(ls:*)"]}}}
        policies = PolicyCatalog.from_baseline_dict(data)
        assert policies[0].tier == 0

    def test_group_without_rules_is_skipped(self) -> None:
        data = {"groups": {"empty": {"tier": 1, "description": "no rules"}}}
        assert PolicyCatalog.from_baseline_dict(data) == []

    def test_non_dict_group_is_skipped(self) -> None:
        data = {"groups": {"broken": ["not", "a", "dict"]}}
        assert PolicyCatalog.from_baseline_dict(data) == []

    def test_non_string_rule_is_skipped(self) -> None:
        data = {"groups": {"mixed": {"tier": 1, "rules": ["Bash(ls:*)", 42, None]}}}
        policies = PolicyCatalog.from_baseline_dict(data)
        assert [p.signature for p in policies] == ["Bash(ls:*)"]

    @pytest.mark.parametrize("data", [{}, {"groups": {}}, {"groups": None}, {"groups": "x"}])
    def test_empty_or_malformed_groups_returns_empty(self, data: dict) -> None:
        assert PolicyCatalog.from_baseline_dict(data) == []


class TestPolicyCatalogLoad:
    def _write(self, tmp_path: Path, data: dict) -> Path:
        p = tmp_path / "baseline.yaml"
        p.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return p

    def test_load_parses_yaml_file(self, tmp_path: Path) -> None:
        path = self._write(tmp_path, _BASELINE)
        policies = PolicyCatalog.load(path)
        assert [p.signature for p in policies] == [
            "Bash(git status:*)",
            "Bash(git commit:*)",
            "Bash(docker ps:*)",
            "Bash(sudo:*)",
        ]

    def test_load_applies_source(self, tmp_path: Path) -> None:
        path = self._write(tmp_path, _BASELINE)
        policies = PolicyCatalog.load(path, source=PolicySource.USER_PRIVATE)
        assert all(p.source == PolicySource.USER_PRIVATE for p in policies)

    def test_load_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert PolicyCatalog.load(tmp_path / "nope.yaml") == []

    def test_load_malformed_yaml_returns_empty(self, tmp_path: Path) -> None:
        p = tmp_path / "baseline.yaml"
        p.write_text("{not: valid: yaml:", encoding="utf-8")
        assert PolicyCatalog.load(p) == []

    def test_load_non_mapping_yaml_returns_empty(self, tmp_path: Path) -> None:
        p = tmp_path / "baseline.yaml"
        p.write_text(yaml.safe_dump(["a", "list"]), encoding="utf-8")
        assert PolicyCatalog.load(p) == []

    def test_load_real_baseline_catalog(self) -> None:
        # The shipped catalog must parse into a non-trivial policy set so the
        # GH-271 pipeline can consume it directly.
        baseline = (
            Path(__file__).resolve().parents[3]
            / "src/dev10x/skills/permission/baseline-permissions.yaml"
        )
        policies = PolicyCatalog.load(baseline)
        assert len(policies) > 50
        assert all(isinstance(p, Policy) for p in policies)
        assert any(p.group == "git-core" for p in policies)
