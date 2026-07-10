"""Tests for the PAP-5 investigator/auditor Policy protocol (GH-802)."""

from __future__ import annotations

from dev10x.domain.common.policy import (
    Policy,
    PolicyAssessment,
    PolicyEffect,
    PolicyScope,
    PolicySource,
)
from dev10x.domain.common.policy_resolution import attach_assessments, resolve_effect
from dev10x.skills.permission_investigator.policy_report import (
    auditor_assessment,
    investigator_assessment,
    render_policy_report,
)


def _policy(*, rule: str, context: str = "") -> Policy:
    return Policy.from_rule_str(
        rule,
        tier=1,
        source=PolicySource.PLUGIN_DEFAULT,
        scope=PolicyScope(context=context),
    )


class TestAssessmentConstructors:
    def test_investigator_assessment_shape(self) -> None:
        assessment = investigator_assessment(status="prompted", note="rule present but asked")
        assert assessment == PolicyAssessment(
            kind="investigator", verdict="prompted", note="rule present but asked"
        )

    def test_auditor_assessment_shape(self) -> None:
        assessment = auditor_assessment(classification="DEAD_RULE")
        assert assessment == PolicyAssessment(kind="auditor", verdict="DEAD_RULE", note="")


class TestAttachAssessments:
    def test_records_attach_to_matching_signature(self) -> None:
        policy = _policy(rule="Bash(git status:*)")
        records = {"Bash(git status:*)": (investigator_assessment(status="matched"),)}
        (attached,) = attach_assessments(policies=[policy], records=records)
        assert attached.assessments == (
            PolicyAssessment(kind="investigator", verdict="matched", note=""),
        )

    def test_existing_assessments_are_preserved(self) -> None:
        existing = auditor_assessment(classification="HOOK_ENABLED")
        policy = Policy.from_rule_str(
            "Bash(rg:*)",
            tier=1,
            source=PolicySource.PLUGIN_DEFAULT,
            assessments=(existing,),
        )
        records = {"Bash(rg:*)": (investigator_assessment(status="matched"),)}
        (attached,) = attach_assessments(policies=[policy], records=records)
        assert attached.assessments[0] == existing
        assert len(attached.assessments) == 2

    def test_policies_without_records_pass_through(self) -> None:
        policy = _policy(rule="Bash(ls:*)")
        (attached,) = attach_assessments(policies=[policy], records={})
        assert attached is policy


class TestRenderPolicyReport:
    def test_report_references_typed_policy_entries(self) -> None:
        policy = _policy(rule="Bash(git status:*)")
        records = {
            "Bash(git status:*)": (
                investigator_assessment(status="prompted", note="enumerated-tool gap"),
                auditor_assessment(classification="DEAD_RULE"),
            )
        }
        lines = render_policy_report(
            policies=attach_assessments(policies=[policy], records=records)
        )
        assert lines == [
            "Bash(git status:*) [tier 1, plugin-default, allow]"
            " — investigator:prompted (enumerated-tool gap); auditor:DEAD_RULE"
        ]

    def test_unassessed_policies_are_omitted(self) -> None:
        assert render_policy_report(policies=[_policy(rule="Bash(ls:*)")]) == []


class TestSkillContextGating:
    def test_context_scoped_policy_applies_only_in_its_context(self) -> None:
        policy = _policy(rule="Bash(git push:*)", context="Dev10x:git")
        signature = "Bash(git push origin main)"
        assert (
            resolve_effect(policies=[policy], signature=signature, context="Dev10x:git")
            == PolicyEffect.ALLOW
        )
        assert resolve_effect(policies=[policy], signature=signature) is None
        assert (
            resolve_effect(policies=[policy], signature=signature, context="Dev10x:review") is None
        )

    def test_unscoped_policy_applies_in_any_context(self) -> None:
        policy = _policy(rule="Bash(git status:*)")
        signature = "Bash(git status)"
        assert (
            resolve_effect(policies=[policy], signature=signature, context="Dev10x:git")
            == PolicyEffect.ALLOW
        )
        assert resolve_effect(policies=[policy], signature=signature) == PolicyEffect.ALLOW
