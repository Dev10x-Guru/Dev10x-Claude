"""Investigator/auditor findings as Policy assessments (PAP-5, GH-802).

The permission-investigator matrix runs and the permission-auditor
classification passes both judge rules — but before PAP-5 their output
was prose keyed on bare rule strings. This module is the protocol
surface both tools report through: findings become
:class:`PolicyAssessment` records attached to the policies they judge
(via :func:`dev10x.domain.common.policy_resolution.attach_assessments`),
and the report renders each finding against its typed Policy entry —
signature, tier, source, and effect — instead of a bare string.
"""

from __future__ import annotations

from dev10x.domain.common.policy import Policy, PolicyAssessment

INVESTIGATOR_KIND = "investigator"
AUDITOR_KIND = "auditor"


def investigator_assessment(*, status: str, note: str = "") -> PolicyAssessment:
    """Record one matrix-cell outcome (e.g. ``matched``, ``prompted``)."""
    return PolicyAssessment(kind=INVESTIGATOR_KIND, verdict=status, note=note)


def auditor_assessment(*, classification: str, note: str = "") -> PolicyAssessment:
    """Record one auditor classification (e.g. ``HOOK_ENABLED``, ``DEAD_RULE``)."""
    return PolicyAssessment(kind=AUDITOR_KIND, verdict=classification, note=note)


def render_policy_report(*, policies: list[Policy]) -> list[str]:
    """One line per assessed policy, referencing the typed entry."""
    lines: list[str] = []
    for policy in policies:
        if not policy.assessments:
            continue
        header = (
            f"{policy.signature}"
            f" [tier {policy.tier}, {policy.source.value}, {policy.effect.value}]"
        )
        findings = "; ".join(_format_assessment(assessment=a) for a in policy.assessments)
        lines.append(f"{header} — {findings}")
    return lines


def _format_assessment(*, assessment: PolicyAssessment) -> str:
    rendered = f"{assessment.kind}:{assessment.verdict}"
    if assessment.note:
        rendered = f"{rendered} ({assessment.note})"
    return rendered


__all__ = [
    "AUDITOR_KIND",
    "INVESTIGATOR_KIND",
    "auditor_assessment",
    "investigator_assessment",
    "render_policy_report",
]
