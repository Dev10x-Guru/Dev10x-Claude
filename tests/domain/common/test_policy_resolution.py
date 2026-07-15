"""Tests for the policy precedence engine (PAP-1, GH-798).

Executable spec for 3-tier resolution (project-local > user-private >
plugin-default) and the forbid-wins rule. The corpus-driven class runs
the PAP-0 fixture corpus (GH-797) through the engine: each case's
``source_tier``/``effect`` pair must survive layering against a
conflicting lower-precedence policy, and each case's vocabulary must
round-trip through the domain enums without falling back to defaults.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dev10x.domain.common.policy import (
    Policy,
    PolicyEffect,
    PolicyLifecycle,
    PolicySensitivity,
    PolicySource,
)
from dev10x.domain.common.policy_resolution import (
    PRECEDENCE,
    load_policy_layers,
    resolve_effect,
)

SIGNATURE = "Bash(git status --porcelain)"


def _policy(
    *,
    effect: PolicyEffect,
    source: PolicySource,
    rule: str = "Bash(git status:*)",
    lifecycle: PolicyLifecycle = PolicyLifecycle.ACTIVE,
    enabled: bool = True,
) -> Policy:
    return Policy.from_rule_str(
        rule,
        tier=1,
        source=source,
        effect=effect,
        lifecycle=lifecycle,
        enabled=enabled,
    )


class TestPrecedenceOrder:
    def test_precedence_lists_all_sources_highest_first(self) -> None:
        assert PRECEDENCE == (
            PolicySource.PROJECT_LOCAL,
            PolicySource.USER_PRIVATE,
            PolicySource.PLUGIN_DEFAULT,
        )


class TestForbidWins:
    def test_plugin_deny_beats_project_allow(self) -> None:
        policies = [
            _policy(effect=PolicyEffect.DENY, source=PolicySource.PLUGIN_DEFAULT),
            _policy(effect=PolicyEffect.ALLOW, source=PolicySource.PROJECT_LOCAL),
        ]
        assert resolve_effect(policies=policies, signature=SIGNATURE) == PolicyEffect.DENY

    def test_project_deny_beats_plugin_allow(self) -> None:
        policies = [
            _policy(effect=PolicyEffect.ALLOW, source=PolicySource.PLUGIN_DEFAULT),
            _policy(effect=PolicyEffect.DENY, source=PolicySource.PROJECT_LOCAL),
        ]
        assert resolve_effect(policies=policies, signature=SIGNATURE) == PolicyEffect.DENY

    def test_deny_at_middle_tier_wins(self) -> None:
        policies = [
            _policy(effect=PolicyEffect.ALLOW, source=PolicySource.PROJECT_LOCAL),
            _policy(effect=PolicyEffect.DENY, source=PolicySource.USER_PRIVATE),
        ]
        assert resolve_effect(policies=policies, signature=SIGNATURE) == PolicyEffect.DENY


class TestTierPrecedence:
    def test_project_allow_beats_user_ask(self) -> None:
        policies = [
            _policy(effect=PolicyEffect.ASK, source=PolicySource.USER_PRIVATE),
            _policy(effect=PolicyEffect.ALLOW, source=PolicySource.PROJECT_LOCAL),
        ]
        assert resolve_effect(policies=policies, signature=SIGNATURE) == PolicyEffect.ALLOW

    def test_user_ask_beats_plugin_allow(self) -> None:
        policies = [
            _policy(effect=PolicyEffect.ALLOW, source=PolicySource.PLUGIN_DEFAULT),
            _policy(effect=PolicyEffect.ASK, source=PolicySource.USER_PRIVATE),
        ]
        assert resolve_effect(policies=policies, signature=SIGNATURE) == PolicyEffect.ASK

    def test_ask_beats_allow_within_one_tier(self) -> None:
        policies = [
            _policy(effect=PolicyEffect.ALLOW, source=PolicySource.PLUGIN_DEFAULT),
            _policy(effect=PolicyEffect.ASK, source=PolicySource.PLUGIN_DEFAULT),
        ]
        assert resolve_effect(policies=policies, signature=SIGNATURE) == PolicyEffect.ASK


class TestEffectiveness:
    def test_disabled_policy_is_ignored(self) -> None:
        policies = [
            _policy(effect=PolicyEffect.DENY, source=PolicySource.PROJECT_LOCAL, enabled=False),
            _policy(effect=PolicyEffect.ALLOW, source=PolicySource.PLUGIN_DEFAULT),
        ]
        assert resolve_effect(policies=policies, signature=SIGNATURE) == PolicyEffect.ALLOW

    def test_deprecated_policy_is_ignored(self) -> None:
        policies = [
            _policy(
                effect=PolicyEffect.DENY,
                source=PolicySource.PROJECT_LOCAL,
                lifecycle=PolicyLifecycle.DEPRECATED,
            ),
        ]
        assert resolve_effect(policies=policies, signature=SIGNATURE) is None

    def test_candidate_policy_participates(self) -> None:
        policies = [
            _policy(
                effect=PolicyEffect.ASK,
                source=PolicySource.USER_PRIVATE,
                lifecycle=PolicyLifecycle.CANDIDATE,
            ),
        ]
        assert resolve_effect(policies=policies, signature=SIGNATURE) == PolicyEffect.ASK


class TestNoMatch:
    def test_empty_policy_set_resolves_to_none(self) -> None:
        assert resolve_effect(policies=[], signature=SIGNATURE) is None

    def test_unmatched_signature_resolves_to_none(self) -> None:
        policies = [_policy(effect=PolicyEffect.ALLOW, source=PolicySource.PLUGIN_DEFAULT)]
        assert resolve_effect(policies=policies, signature="Bash(rm -rf /)") is None


class TestLoadPolicyLayers:
    def _write(self, path: Path, rule: str) -> Path:
        data = {"groups": {"g": {"tier": 1, "rules": [rule]}}}
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return path

    def test_layers_are_tagged_with_their_source(self, tmp_path: Path) -> None:
        plugin = self._write(tmp_path / "plugin.yaml", "Bash(ls:*)")
        user = self._write(tmp_path / "user.yaml", "Bash(rg:*)")
        project = self._write(tmp_path / "project.yaml", "Bash(jq:*)")
        policies = load_policy_layers(plugin_path=plugin, user_path=user, project_path=project)
        by_source = {policy.source: policy.signature for policy in policies}
        assert by_source == {
            PolicySource.PLUGIN_DEFAULT: "Bash(ls:*)",
            PolicySource.USER_PRIVATE: "Bash(rg:*)",
            PolicySource.PROJECT_LOCAL: "Bash(jq:*)",
        }

    def test_omitted_layers_contribute_nothing(self, tmp_path: Path) -> None:
        plugin = self._write(tmp_path / "plugin.yaml", "Bash(ls:*)")
        policies = load_policy_layers(plugin_path=plugin)
        assert [policy.source for policy in policies] == [PolicySource.PLUGIN_DEFAULT]

    def test_missing_file_contributes_nothing(self, tmp_path: Path) -> None:
        assert load_policy_layers(plugin_path=tmp_path / "nope.yaml") == []

    def test_no_layers_yields_empty_set(self) -> None:
        assert load_policy_layers() == []

    def _write_flat(self, path: Path, *, allow: list[str], deny: list[str] | None = None) -> Path:
        data = {"base_permissions": allow, "base_denies": deny or []}
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return path

    def test_flat_user_layer_is_normalized_and_tagged_user_private(self, tmp_path: Path) -> None:
        user = self._write_flat(tmp_path / "user.yaml", allow=["Bash(rg:*)"])
        policies = load_policy_layers(user_path=user)
        assert len(policies) == 1
        assert policies[0].signature == "Bash(rg:*)"
        assert policies[0].source is PolicySource.USER_PRIVATE
        assert policies[0].effect is PolicyEffect.ALLOW

    def test_flat_project_layer_is_normalized_and_tagged_project_local(
        self, tmp_path: Path
    ) -> None:
        project = self._write_flat(
            tmp_path / "project.yaml", allow=["Bash(jq:*)"], deny=["Bash(rm -rf /:*)"]
        )
        policies = load_policy_layers(project_path=project)
        by_signature = {p.signature: p for p in policies}
        assert by_signature["Bash(jq:*)"].source is PolicySource.PROJECT_LOCAL
        assert by_signature["Bash(jq:*)"].effect is PolicyEffect.ALLOW
        assert by_signature["Bash(rm -rf /:*)"].source is PolicySource.PROJECT_LOCAL
        assert by_signature["Bash(rm -rf /:*)"].effect is PolicyEffect.DENY

    def test_flat_layer_rules_resolve_through_resolve_effect(self, tmp_path: Path) -> None:
        project = self._write_flat(tmp_path / "project.yaml", allow=["Bash(jq:*)"])
        policies = load_policy_layers(project_path=project)
        assert (
            resolve_effect(policies=policies, signature="Bash(jq --version)") == PolicyEffect.ALLOW
        )

    def test_flat_plugin_layer_keeps_plugin_default_source(self, tmp_path: Path) -> None:
        plugin = self._write_flat(tmp_path / "plugin.yaml", allow=["Bash(ls:*)"])
        policies = load_policy_layers(plugin_path=plugin)
        assert policies[0].source is PolicySource.PLUGIN_DEFAULT

    def test_structured_layer_with_groups_is_not_double_migrated(self, tmp_path: Path) -> None:
        path = tmp_path / "structured.yaml"
        data = {
            "groups": {"g": {"tier": 1, "rules": ["Bash(ls:*)"]}},
            "base_permissions": ["Bash(rg:*)"],
        }
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        policies = load_policy_layers(user_path=path)
        assert [policy.signature for policy in policies] == ["Bash(ls:*)"]


_CORPUS_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "permission-policy"


def _corpus_cases() -> list[tuple[str, dict]]:
    cases: list[tuple[str, dict]] = []
    for path in sorted(_CORPUS_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        cases.extend((case["id"], case) for case in data["cases"])
    return cases


_CASES = _corpus_cases()


def _lower_tiers(source: PolicySource) -> list[PolicySource]:
    return list(PRECEDENCE[PRECEDENCE.index(source) + 1 :])


class TestCorpusDrivenResolution:
    """The PAP-0 corpus is the acceptance gate for the PAP-1 engine (GH-798)."""

    @pytest.mark.parametrize(("case_id", "case"), _CASES, ids=[i for i, _ in _CASES])
    def test_vocabulary_round_trips_without_default_fallback(
        self, case_id: str, case: dict
    ) -> None:
        assert PolicyEffect.from_yaml(case["effect"]).value == case["effect"]
        assert PolicySource.from_yaml(case["source_tier"]).value == case["source_tier"]
        assert PolicySensitivity.from_yaml(case["sensitivity"]).value == case["sensitivity"]

    @pytest.mark.parametrize(("case_id", "case"), _CASES, ids=[i for i, _ in _CASES])
    def test_case_effect_survives_layering(self, case_id: str, case: dict) -> None:
        effect = PolicyEffect.from_yaml(case["effect"])
        source = PolicySource.from_yaml(case["source_tier"])
        signature = f"Case({case_id})"
        governing = Policy.from_rule_str(
            signature,
            tier=1,
            source=source,
            effect=effect,
            sensitivity=PolicySensitivity.from_yaml(case["sensitivity"]),
        )
        conflict_effect = PolicyEffect.ASK if effect is PolicyEffect.ALLOW else PolicyEffect.ALLOW
        conflicts = [
            Policy.from_rule_str(signature, tier=1, source=lower, effect=conflict_effect)
            for lower in _lower_tiers(source)
        ]
        resolved = resolve_effect(policies=[governing, *conflicts], signature=signature)
        assert resolved == effect
