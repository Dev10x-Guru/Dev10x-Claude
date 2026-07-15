"""Deterministic security auditor for allow rules (PAP-6, GH-867).

The permission-auditor *agent* (``agents/permission-auditor.md``)
classifies allow rules into an 8-token security vocabulary
(``OVERLY_BROAD``, ``CONTRADICTS_POLICY``, ``SKILL_REQUIRED``,
``HOOK_ENABLED``, ``DEAD_RULE``, ``WILDCARD_ESCAPE``,
``PRIVILEGE_ESCALATION``, ``REDUNDANT``) as prose.
:func:`~dev10x.skills.permission_investigator.policy_report.auditor_assessment`
(PAP-5) is the typed surface for those classifications, but until now it
had no Python producer — the "auditor emits PolicyAssessment" clause of
GH-819 was only half-wired.

This module computes the **shape-decidable subset** of that vocabulary —
the categories a rule's own grammar settles without security judgement —
and renders each finding against its typed :class:`Policy` via
:func:`render_policy_report`, so ``dev10x permission audit`` is a real
production caller. The judgement-heavy categories (``CONTRADICTS_POLICY``,
``PRIVILEGE_ESCALATION``, ``SKILL_REQUIRED``, and hook-dependent
``DEAD_RULE``) stay with the Claude-driven agent; this path never guesses
them.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from dev10x.domain.common.allow_rule import AllowRule, AllowRuleLoader
from dev10x.domain.common.policy import Policy, PolicyAssessment, PolicySource
from dev10x.domain.common.policy_resolution import attach_assessments
from dev10x.skills.permission.clean_project_files import HOOK_ENABLED_INNER_PREFIXES
from dev10x.skills.permission_investigator.policy_report import (
    auditor_assessment,
    render_policy_report,
)

OVERLY_BROAD = "OVERLY_BROAD"
WILDCARD_ESCAPE = "WILDCARD_ESCAPE"
HOOK_ENABLED = "HOOK_ENABLED"
REDUNDANT = "REDUNDANT"

_BARE_WILDCARDS = frozenset({"*", ".*", "**"})
_ENV_PREFIX_RE = re.compile(r"^[A-Z_][A-Z0-9_]*=")

_NOTES: dict[str, str] = {
    OVERLY_BROAD: "bare wildcard — permits arbitrary commands; narrow to specific prefixes",
    WILDCARD_ESCAPE: "prefix pre-approves an arbitrary command body (env-assignment / loop)",
    HOOK_ENABLED: "covered by an educational hook redirect — removing it degrades to a raw prompt",
    REDUNDANT: "duplicate of, or subsumed by, a broader rule in the same set",
}


def _bash_prefix(rule: AllowRule) -> str:
    """The command prefix a Bash ``:*`` rule pre-approves (``""`` for non-Bash)."""
    if rule.tool == "Bash" and rule.pattern.endswith(":*"):
        return rule.pattern[:-2]
    return ""


def _representative_value(rule: AllowRule) -> str:
    """A concrete-ish value a rule governs, for subsumption comparison."""
    if rule.tool == "Bash" and rule.pattern.endswith(":*"):
        return rule.pattern[:-2]
    if rule.pattern.endswith("**"):
        return rule.pattern[:-2]
    return rule.pattern


def _is_overly_broad(rule: AllowRule) -> bool:
    if rule.pattern in _BARE_WILDCARDS:
        return True
    return rule.tool == "Bash" and rule.pattern.endswith(":*") and _bash_prefix(rule).strip() == ""


def _is_wildcard_escape(rule: AllowRule) -> bool:
    if rule.tool != "Bash":
        return False
    prefix = _bash_prefix(rule)
    return bool(_ENV_PREFIX_RE.match(prefix)) or prefix.startswith("for ")


def _is_hook_enabled(rule: AllowRule) -> bool:
    if rule.tool != "Bash":
        return False
    prefix = _bash_prefix(rule)
    return any(prefix.startswith(hook) for hook in HOOK_ENABLED_INNER_PREFIXES)


def _is_redundant(rule: AllowRule, *, rules: list[AllowRule]) -> bool:
    duplicates = sum(1 for other in rules if other.raw == rule.raw)
    if duplicates > 1:
        return True
    value = _representative_value(rule)
    for other in rules:
        if other.raw == rule.raw or other.tool != rule.tool:
            continue
        if other.matches_prefix(value) and not rule.matches_prefix(_representative_value(other)):
            return True
    return False


def classify_allow_rule(rule: AllowRule, *, rules: list[AllowRule]) -> str | None:
    """Classify one allow rule into the shape-decidable token subset.

    Returns ``None`` for a rule whose grammar raises no deterministic
    concern (the agent's ``SAFE`` and judgement-only categories). The
    checks are ordered by severity so the most dangerous shape wins when
    several apply.
    """
    if _is_overly_broad(rule):
        return OVERLY_BROAD
    if _is_wildcard_escape(rule):
        return WILDCARD_ESCAPE
    if _is_hook_enabled(rule):
        return HOOK_ENABLED
    if _is_redundant(rule, rules=rules):
        return REDUNDANT
    return None


def audit_policies(
    *,
    rules: list[AllowRule],
    catalog_policies: dict[str, Policy] | None = None,
) -> list[Policy]:
    """Classify ``rules`` and return the assessed Policies (finding order).

    Each classified rule becomes an :func:`auditor_assessment` keyed by its
    signature; identical (signature, classification) pairs collapse so a
    duplicated rule renders once. A rule matching a ``catalog_policies``
    entry is rendered against that typed entry (its real tier/source/
    effect); an off-catalog settings rule falls back to an unscoped tier-0
    project-local Policy. Rules with no finding are omitted.
    """
    catalog_policies = catalog_policies or {}
    records: dict[str, list[PolicyAssessment]] = {}
    ordered: list[str] = []
    for rule in rules:
        token = classify_allow_rule(rule, rules=rules)
        if token is None:
            continue
        signature = rule.raw
        if signature not in records:
            records[signature] = []
            ordered.append(signature)
        assessment = auditor_assessment(classification=token, note=_NOTES[token])
        if assessment not in records[signature]:
            records[signature].append(assessment)
    policies = [
        catalog_policies.get(signature)
        or Policy.from_rule_str(signature, tier=0, source=PolicySource.PROJECT_LOCAL)
        for signature in ordered
    ]
    return attach_assessments(
        policies=policies,
        records={signature: tuple(items) for signature, items in records.items()},
    )


def audit_report(
    *,
    rules: list[AllowRule],
    catalog_policies: dict[str, Policy] | None = None,
) -> list[str]:
    """Render the auditor findings as report lines (empty-input tolerant)."""
    policies = audit_policies(rules=rules, catalog_policies=catalog_policies)
    lines = render_policy_report(policies=policies)
    if not lines:
        return ["No auditor findings — every allow rule is SAFE by shape."]
    return ["# Permission Audit (PAP-6 auditor assessments)", "", *lines]


def rules_from_settings(settings_files: Iterable[str | Path]) -> list[AllowRule]:
    """Parse allow rules from settings JSON files into AllowRules."""
    rules: list[AllowRule] = []
    for path in settings_files:
        rules.extend(AllowRule.parse(raw) for raw in AllowRuleLoader.load(path))
    return rules


__all__ = [
    "HOOK_ENABLED",
    "OVERLY_BROAD",
    "REDUNDANT",
    "WILDCARD_ESCAPE",
    "audit_policies",
    "audit_report",
    "classify_allow_rule",
    "rules_from_settings",
]
