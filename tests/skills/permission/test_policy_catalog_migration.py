"""Tests for the flat-catalog → Policy migration (PAP-2, GH-799).

The parity class is the acceptance gate: the migrated catalog must
project back to the exact flat lists ``ensure_base`` shipped before the
migration, so settings.json output is unchanged until the PAP-3
renderer lands. The corpus class asserts the migrated catalog already
decides the PAP-0 fixture cases whose governing rules it carries.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dev10x.domain.common.policy import (
    Policy,
    PolicyEffect,
    PolicySensitivity,
    PolicySource,
)
from dev10x.domain.common.policy_resolution import resolve_effect
from dev10x.skills.permission.policy_catalog_migration import (
    CLAUDE_AI_MCP_GROUP,
    DEFAULT_TIER,
    FENCE_TOOL_PROBE_GROUP,
    flat_allow_rules,
    flat_deny_rules,
    load_baseline_policies,
    migrate_flat_config,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PROJECTS_YAML = _REPO_ROOT / "skills" / "upgrade-cleanup" / "projects.yaml"


def _shipped_config() -> dict:
    return yaml.safe_load(_PROJECTS_YAML.read_text(encoding="utf-8"))


_CONFIG = _shipped_config()
_POLICIES = migrate_flat_config(config=_CONFIG)


class TestFlatParity:
    """The compatibility shim reproduces the shipped flat lists exactly."""

    def test_allow_projection_matches_base_permissions(self) -> None:
        assert flat_allow_rules(policies=_POLICIES) == _CONFIG["base_permissions"]

    def test_deny_projection_matches_base_denies(self) -> None:
        assert flat_deny_rules(policies=_POLICIES) == _CONFIG["base_denies"]

    def test_every_flat_rule_became_a_policy(self) -> None:
        expected = len(_CONFIG["base_permissions"]) + len(_CONFIG["base_denies"])
        assert len(_POLICIES) == expected

    def test_all_policies_are_plugin_default(self) -> None:
        assert all(p.source is PolicySource.PLUGIN_DEFAULT for p in _POLICIES)

    def test_policy_id_is_the_rule_string(self) -> None:
        assert all(p.id == p.signature for p in _POLICIES)


class TestMigrationClassification:
    def test_base_denies_carry_deny_effect(self) -> None:
        config = {"base_permissions": ["Bash(ls:*)"], "base_denies": ["Bash(sudo:*)"]}
        policies = migrate_flat_config(config=config, baseline_policies=[])
        assert [p.effect for p in policies] == [PolicyEffect.ALLOW, PolicyEffect.DENY]

    def test_baseline_match_enriches_tier_group_sensitivity(self) -> None:
        baseline = [
            Policy.from_rule_str(
                "Bash(git status:*)",
                tier=1,
                source=PolicySource.PLUGIN_DEFAULT,
                sensitivity=PolicySensitivity.BENIGN,
                group="git-core",
            )
        ]
        config = {"base_permissions": ["Bash(git status:*)"]}
        (policy,) = migrate_flat_config(config=config, baseline_policies=baseline)
        assert policy.tier == 1
        assert policy.group == "git-core"
        assert policy.sensitivity is PolicySensitivity.BENIGN

    def test_unmatched_rule_gets_default_tier(self) -> None:
        config = {"base_permissions": ["Bash(some-tool:*)"]}
        (policy,) = migrate_flat_config(config=config, baseline_policies=[])
        assert policy.tier == DEFAULT_TIER
        assert policy.group == ""

    def test_connector_read_tool_is_grouped_and_benign(self) -> None:
        config = {"base_permissions": ["mcp__claude_ai_Linear__get_issue"]}
        (policy,) = migrate_flat_config(config=config, baseline_policies=[])
        assert policy.group == CLAUDE_AI_MCP_GROUP
        assert policy.sensitivity is PolicySensitivity.BENIGN

    def test_connector_write_tool_stays_unspecified(self) -> None:
        config = {"base_permissions": ["mcp__claude_ai_Linear__save_comment"]}
        (policy,) = migrate_flat_config(config=config, baseline_policies=[])
        assert policy.group == CLAUDE_AI_MCP_GROUP
        assert policy.sensitivity is PolicySensitivity.UNSPECIFIED

    def test_linear_server_variant_is_a_connector(self) -> None:
        config = {"base_permissions": ["mcp__linear-server__list_issues"]}
        (policy,) = migrate_flat_config(config=config, baseline_policies=[])
        assert policy.group == CLAUDE_AI_MCP_GROUP
        assert policy.sensitivity is PolicySensitivity.BENIGN

    def test_fence_tool_probe_is_grouped_and_reversible(self) -> None:
        config = {"base_permissions": ["Bash(npx --version)"]}
        (policy,) = migrate_flat_config(config=config, baseline_policies=[])
        assert policy.group == FENCE_TOOL_PROBE_GROUP
        assert policy.reversible is True

    def test_non_fence_version_probe_is_not_grouped(self) -> None:
        config = {"base_permissions": ["Bash(git --version)"]}
        (policy,) = migrate_flat_config(config=config, baseline_policies=[])
        assert policy.group != FENCE_TOOL_PROBE_GROUP

    def test_baseline_group_wins_over_bootstrap_passes(self) -> None:
        baseline = [
            Policy.from_rule_str(
                "mcp__claude_ai_Sentry__search_issues",
                tier=2,
                source=PolicySource.PLUGIN_DEFAULT,
                sensitivity=PolicySensitivity.BENIGN,
                group="mcp-sentry-readonly",
            )
        ]
        config = {"base_permissions": ["mcp__claude_ai_Sentry__search_issues"]}
        (policy,) = migrate_flat_config(config=config, baseline_policies=baseline)
        assert policy.group == "mcp-sentry-readonly"

    def test_non_string_and_missing_entries_are_skipped(self) -> None:
        config = {"base_permissions": ["Bash(ls:*)", 42, None], "base_denies": "oops"}
        policies = migrate_flat_config(config=config, baseline_policies=[])
        assert [p.signature for p in policies] == ["Bash(ls:*)"]

    def test_empty_config_migrates_to_empty_catalog(self) -> None:
        assert migrate_flat_config(config={}, baseline_policies=[]) == []


class TestBaselineEnrichmentAgainstShippedCatalogs:
    def test_shipped_baseline_loads_for_enrichment(self) -> None:
        assert len(load_baseline_policies()) > 50

    def test_git_status_inherits_git_core_group(self) -> None:
        policy = next(p for p in _POLICIES if p.signature == "Bash(git status:*)")
        assert policy.group == "git-core"
        assert policy.tier == 1


_CORPUS_DIR = _REPO_ROOT / "tests" / "fixtures" / "permission-policy"

# PAP-0 cases the migrated plugin-default catalog must already decide.
# Ask-effect cases are absent by design: the shipped flat catalog is an
# allow/deny catalog; the ask tier arrives with later PAP phases.
_DECIDED_BY_CATALOG = {
    "GH-271/#282": PolicyEffect.ALLOW,
    "GH-271/#2": PolicyEffect.ALLOW,
    "GH-326/base-deny-sudo": PolicyEffect.DENY,
    "baseline/dev10x-cli-mktmp": PolicyEffect.ALLOW,
    "GH-271/#150": PolicyEffect.ALLOW,
    "routing/git-commit": PolicyEffect.ALLOW,
}


def _corpus_case(case_id: str) -> tuple[str, dict]:
    for path in sorted(_CORPUS_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for case in data["cases"]:
            if case["id"] == case_id:
                return data["surface"], case
    raise AssertionError(f"corpus case {case_id} not found")


def _signature(surface: str, case: dict) -> str:
    raw = case["input"]
    if surface == "mcp":
        return raw.split("(", 1)[0]
    if surface == "skill-invocation":
        return raw
    return f"Bash({raw})"


class TestCorpusCasesDecidedByMigratedCatalog:
    @pytest.mark.parametrize(
        ("case_id", "expected"),
        sorted(_DECIDED_BY_CATALOG.items()),
        ids=sorted(_DECIDED_BY_CATALOG),
    )
    def test_migrated_catalog_resolves_corpus_case(
        self, case_id: str, expected: PolicyEffect
    ) -> None:
        surface, case = _corpus_case(case_id)
        signature = _signature(surface, case)
        assert resolve_effect(policies=_POLICIES, signature=signature) == expected
        assert PolicyEffect.from_yaml(case["effect"]) == expected
