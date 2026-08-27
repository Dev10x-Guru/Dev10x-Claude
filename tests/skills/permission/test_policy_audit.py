"""Tests for the deterministic allow-rule auditor (PAP-6, GH-867)."""

from __future__ import annotations

import json
from pathlib import Path

from dev10x.domain.common.accepted_findings import AcceptedFinding
from dev10x.domain.common.allow_rule import AllowRule
from dev10x.domain.common.policy import Policy, PolicySource
from dev10x.skills.permission import policy_audit


def _rules(*raws: str) -> list[AllowRule]:
    return [AllowRule.parse(raw) for raw in raws]


def _classify(raw: str, *, alongside: tuple[str, ...] = ()) -> str | None:
    rules = _rules(raw, *alongside)
    return policy_audit.classify_allow_rule(rules[0], rules=rules)


class TestClassifyAllowRule:
    def test_bare_bash_wildcard_is_overly_broad(self) -> None:
        assert _classify("Bash(:*)") == policy_audit.OVERLY_BROAD

    def test_star_pattern_is_overly_broad(self) -> None:
        assert _classify("Bash(*)") == policy_audit.OVERLY_BROAD

    def test_path_double_star_is_overly_broad(self) -> None:
        assert _classify("Read(**)") == policy_audit.OVERLY_BROAD

    def test_env_assignment_prefix_is_wildcard_escape(self) -> None:
        assert _classify("Bash(VAR=:*)") == policy_audit.WILDCARD_ESCAPE

    def test_for_loop_prefix_is_wildcard_escape(self) -> None:
        assert _classify("Bash(for x in:*)") == policy_audit.WILDCARD_ESCAPE

    def test_known_hook_prefix_is_hook_enabled(self) -> None:
        assert _classify("Bash(git push:*)") == policy_audit.HOOK_ENABLED

    def test_exact_duplicate_is_redundant(self) -> None:
        assert _classify("Bash(rg:*)", alongside=("Bash(rg:*)",)) == policy_audit.REDUNDANT

    def test_narrow_rule_subsumed_by_broader_is_redundant(self) -> None:
        assert (
            _classify("Bash(git status:*)", alongside=("Bash(git:*)",)) == policy_audit.REDUNDANT
        )

    def test_broader_rule_is_not_redundant(self) -> None:
        assert _classify("Bash(git:*)", alongside=("Bash(git status:*)",)) is None

    def test_safe_rule_returns_none(self) -> None:
        assert _classify("Bash(rg:*)") is None

    def test_exact_command_rule_without_prefix_is_safe(self) -> None:
        assert _classify("Bash(ls)") is None

    def test_safe_path_rule_returns_none(self) -> None:
        assert _classify("Read(/home/me/project/**)") is None

    def test_narrow_path_glob_subsumed_by_broader_is_redundant(self) -> None:
        assert _classify("Read(/a/b/**)", alongside=("Read(/a/**)",)) == policy_audit.REDUNDANT


class TestAuditPolicies:
    def test_finding_uses_catalog_tier_and_source(self) -> None:
        catalog = {
            "Bash(git push:*)": Policy.from_rule_str(
                "Bash(git push:*)", tier=2, source=PolicySource.PLUGIN_DEFAULT
            )
        }
        (policy,) = policy_audit.audit_policies(
            rules=_rules("Bash(git push:*)"), catalog_policies=catalog
        )
        assert policy.tier == 2
        assert policy.source is PolicySource.PLUGIN_DEFAULT
        assert policy.assessments[0].kind == "auditor"
        assert policy.assessments[0].verdict == policy_audit.HOOK_ENABLED

    def test_off_catalog_rule_falls_back_to_project_local(self) -> None:
        (policy,) = policy_audit.audit_policies(rules=_rules("Bash(:*)"))
        assert policy.source is PolicySource.PROJECT_LOCAL
        assert policy.tier == 0

    def test_duplicate_rule_renders_a_single_assessment(self) -> None:
        policies = policy_audit.audit_policies(rules=_rules("Bash(rg:*)", "Bash(rg:*)"))
        assert len(policies) == 1
        assert len(policies[0].assessments) == 1

    def test_safe_rules_are_omitted(self) -> None:
        assert policy_audit.audit_policies(rules=_rules("Bash(rg:*)")) == []


class TestAuditReport:
    def test_empty_rules_report_clean(self) -> None:
        assert policy_audit.audit_report(rules=[]) == [
            "No auditor findings — every allow rule is SAFE by shape."
        ]

    def test_findings_render_with_header(self) -> None:
        lines = policy_audit.audit_report(rules=_rules("Bash(:*)"))
        assert lines[0] == "# Permission Audit (PAP-6 auditor assessments)"
        assert any("auditor:OVERLY_BROAD" in line for line in lines)


class TestAcceptedFindingSuppression:
    """GH-1053: a ruling the maintainer already made is not re-proposed."""

    BASELINE_PAIR = ("Bash(git reset:*)", "Bash(git reset --hard:*)")

    def test_subsumed_baseline_rule_is_a_finding_without_acceptances(self) -> None:
        outcome = policy_audit.audit_findings(rules=_rules(*self.BASELINE_PAIR), accepted=())
        assert [policy.signature for policy in outcome.reported] == ["Bash(git reset --hard:*)"]
        assert outcome.suppressed == ()

    def test_shipped_acceptance_moves_the_finding_out_of_proposals(self) -> None:
        outcome = policy_audit.audit_findings(rules=_rules(*self.BASELINE_PAIR))
        assert outcome.reported == []
        assert [item.rule for item in outcome.suppressed] == ["Bash(git reset --hard:*)"]
        assert outcome.suppressed[0].classification == policy_audit.REDUNDANT

    def test_branch_deletion_family_is_accepted(self) -> None:
        outcome = policy_audit.audit_findings(
            rules=_rules("Bash(git branch:*)", "Bash(git branch -D:*)")
        )
        assert outcome.reported == []
        assert [item.rule for item in outcome.suppressed] == ["Bash(git branch -D:*)"]

    def test_acceptance_is_scoped_to_its_classification(self) -> None:
        accepted = (
            AcceptedFinding(
                rule="Bash(git reset --hard:*)",
                rationale="only the redundancy verdict",
                classifications=frozenset({"OVERLY_BROAD"}),
            ),
        )
        outcome = policy_audit.audit_findings(rules=_rules(*self.BASELINE_PAIR), accepted=accepted)
        assert [policy.signature for policy in outcome.reported] == ["Bash(git reset --hard:*)"]
        assert outcome.suppressed == ()

    def test_report_lists_suppressions_under_their_own_heading(self) -> None:
        lines = policy_audit.audit_report(rules=_rules(*self.BASELINE_PAIR))
        assert "## Suppressed by accepted-findings (1)" in lines
        assert any("Bash(git reset --hard:*)" in line for line in lines)
        assert any("GH-1053" in line for line in lines)

    def test_report_says_nothing_to_propose_when_all_findings_are_accepted(self) -> None:
        lines = policy_audit.audit_report(rules=_rules(*self.BASELINE_PAIR))
        assert "No auditor findings to propose — every finding is accepted by design." in lines


class TestRulesFromSettings:
    def test_parses_allow_rules_from_settings_file(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.local.json"
        settings.write_text(
            json.dumps({"permissions": {"allow": ["Bash(git push:*)", "Read(**)"]}})
        )
        rules = policy_audit.rules_from_settings([str(settings)])
        assert [rule.raw for rule in rules] == ["Bash(git push:*)", "Read(**)"]
