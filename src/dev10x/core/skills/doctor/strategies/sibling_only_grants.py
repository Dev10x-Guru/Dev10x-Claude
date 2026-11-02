"""Strategy: sibling-only-grants (GH-1711).

A rule approved in one worktree stays in that worktree. ``sync-worktrees``
carries the main checkout's grants into existing worktrees and
``merge-worktree`` copies worktree rules into the main checkout, but only
on an explicit run and only by copying files sideways. The remembered
layer, ``~/.config/Dev10x/granted-permissions.yaml`` (GH-1677), is where
a grant should live so every seeding path propagates it — and nothing
fed sibling-only rules into it.

This strategy diffs the ``settings.local.json`` of every checkout in the
repo family and lists the allow rules some siblings hold and others do
not. Rules pinned to one checkout's path, session noise, rules already
remembered, and rules the spread guard holds back (GH-1790) are left
out. Report only: lifting a rule is the supervisor's call.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dev10x.domain.common.allow_rule import AllowRuleLoader
from dev10x.skills.doctor.strategies.stranded_worktree_rules import own_checkout
from dev10x.skills.doctor.strategy import Context, Finding, Remediation, Strategy
from dev10x.skills.permission.declined_catalog import load_declined_rules
from dev10x.skills.permission.granted_catalog import granted_path, load_granted_rules
from dev10x.skills.permission.merge_worktree_permissions import is_noise, pins_a_checkout
from dev10x.skills.permission.settings_discovery import git_registered_worktrees
from dev10x.skills.permission.spread_guard import hold_reason

GRANT_TOOL = "mcp__plugin_dev10x_cli__permission_grant"


@dataclass(frozen=True)
class LiftGrantRemediation:
    """Remediation payload: remember a sibling-only rule for every checkout.

    Executed through ``permission_grant`` with ``remember=true``, which
    triages the rule first and records it in ``granted-permissions.yaml``.
    """

    rule: str
    granted_path: str

    def to_remediation(self, *, finding: Finding) -> Remediation:
        return Remediation(
            kind="edit_settings",
            target=self.granted_path,
            action={
                "tool": GRANT_TOOL,
                "arguments": {"target": self.rule, "rule": self.rule, "remember": True},
            },
        )


def _family_allow(checkout: Path) -> dict[Path, set[str]]:
    """Each family member's allow rules; unreadable or absent files are skipped."""
    allow: dict[Path, set[str]] = {}
    for member in git_registered_worktrees(checkout):
        rules = AllowRuleLoader.load_optional(member / ".claude" / "settings.local.json")
        if rules is not None:
            allow[member] = {rule for rule in rules if isinstance(rule, str)}
    return allow


def _checkouts(context: Context) -> list[Path]:
    seen: dict[Path, None] = {}
    for path in context.settings_paths:
        checkout = own_checkout(path)
        if checkout is not None:
            seen.setdefault(checkout, None)
    return list(seen)


def detect(context: Context) -> list[Finding]:
    """List rules some siblings hold and others lack, worth lifting once."""
    findings: list[Finding] = []
    seen_families: set[Path] = set()
    for checkout in _checkouts(context):
        allow = _family_allow(checkout)
        if len(allow) < 2:
            continue
        family = list(allow)
        if family[0] in seen_families:
            continue
        seen_families.add(family[0])
        skip = set(load_granted_rules())
        declined = load_declined_rules()
        held_by_some: set[str] = set().union(*allow.values())
        held_by_all: set[str] = set.intersection(*allow.values())
        for rule in sorted(held_by_some - held_by_all):
            if rule in skip or is_noise(rule) or pins_a_checkout(rule, checkouts=family):
                continue
            if hold_reason(rule=rule, declined=declined) is not None:
                continue
            holders = [member for member, rules in allow.items() if rule in rules]
            findings.append(_finding(rule=rule, holders=holders, total=len(family)))
    return findings


def _finding(*, rule: str, holders: list[Path], total: int) -> Finding:
    target = granted_path()
    return Finding(
        strategy_id="sibling-only-grants",
        severity="suggestion",
        location=rule,
        evidence=(
            f"``{rule}`` is granted in {len(holders)} of {total} checkouts "
            f"({', '.join(str(holder) for holder in holders)}); the others "
            "still prompt for it"
        ),
        proposed_fix=(
            f"Call {GRANT_TOOL}(target=rule, rule=rule, remember=true): it triages "
            f"the rule, then records it in {target} so ensure-base and "
            "seed-worktree carry it to every checkout, existing and future."
        ),
        data=LiftGrantRemediation(rule=rule, granted_path=str(target)),
    )


def remediate(finding: Finding) -> Remediation:
    """Propose lifting the rule into the remembered-grant layer."""
    return finding.to_remediation()


STRATEGY = Strategy(
    id="sibling-only-grants",
    description=(
        "List allow rules granted in some checkouts of a repo and missing "
        "from others, and offer to remember each once in "
        "granted-permissions.yaml so every checkout gets it (GH-1711)."
    ),
    detect=detect,
    remediate=remediate,
)
