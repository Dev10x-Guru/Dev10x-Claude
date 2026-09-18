"""Rank permission friction from recorded denials (GH-1406).

Every permission-friction tracker this repo has produced was assembled
by a human reading their own terminal and typing up what they saw, so
the evidence has always been anecdotal: we could not say which friction
was frequent, which was rare, which a release fixed, or which one
regressed.

The taxonomy recorded the cause as "settings-file prompts never reach a
hook". That is true of two of the three prompt paths, not all three.
Resolution runs ``deny -> ask -> allow -> no-match`` and PreToolUse
hooks fire only on what those steps already allowed, so:

===================================  ==========  =================
Path                                 Outcome     Observable
===================================  ==========  =================
Deny rule matches                    blocked     yes (this module)
Ask rule matches                     prompted    no
No rule matches                      prompted    no
Allowed, then PreToolUse blocks      blocked     yes (GH-1095)
===================================  ==========  =================

So this module is **tier 1**: it mines what is already recorded rather
than waiting on a prompt-shown event that no documented harness hook
provides. It answers "which denials actually happen, and in what
proportion" — not "which prompts were shown". The two remaining rows
need harness support this repo does not own, and saying so is better
than shipping a partial that reads as complete.

Counts here are only as old as the retained audit logs, and only cover
machines with auditing on (``DEV10X_HOOK_AUDIT``). A family absent from
a report is unmeasured, never proven frictionless.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from dev10x.skills.permission.catalog_gap import rule_family

PERMISSION_DENIED_HOOK = "permission-denied"

# Records written before GH-1406 carry no tool signature — only wrap-phase
# timing. They are counted separately rather than dropped: a report that
# silently ignored them would understate friction on exactly the machines
# with the longest history.
UNATTRIBUTED = "(unattributed — recorded before GH-1406)"


@dataclass(frozen=True)
class FrictionReport:
    """Denials grouped by rule family, most frequent first."""

    total: int = 0
    unattributed: int = 0
    by_family: list[tuple[str, int]] = field(default_factory=list)
    top_signatures: list[tuple[str, int]] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return self.total == 0

    @property
    def attributed(self) -> int:
        return self.total - self.unattributed


def _is_denial(record: dict[str, Any]) -> bool:
    return record.get("hook") == PERMISSION_DENIED_HOOK


def _signature(record: dict[str, Any]) -> str | None:
    signature = record.get("tool_signature")
    return signature if isinstance(signature, str) and signature else None


def _family(record: dict[str, Any], *, signature: str) -> str:
    # Prefer the family the hook computed: it classified the live
    # signature, so a later change to `rule_family` cannot retroactively
    # reclassify history. Fall back for records written by a hook that
    # recorded a signature but not yet a family.
    recorded = record.get("rule_family")
    if isinstance(recorded, str) and recorded:
        return recorded
    return rule_family(signature)


def build_report(
    *,
    records: list[dict[str, Any]],
    top: int = 10,
) -> FrictionReport:
    """Aggregate PermissionDenied audit records into a ranked report.

    Pure over its input so the ranking is testable without an audit log;
    the CLI owns reading the log and printing the result.
    """
    denials = [record for record in records if _is_denial(record)]
    if not denials:
        return FrictionReport()

    families: Counter[str] = Counter()
    signatures: Counter[str] = Counter()
    unattributed = 0

    for record in denials:
        signature = _signature(record)
        if signature is None:
            unattributed += 1
            continue
        families[_family(record, signature=signature)] += 1
        signatures[signature] += 1

    if unattributed:
        families[UNATTRIBUTED] = unattributed

    return FrictionReport(
        total=len(denials),
        unattributed=unattributed,
        by_family=families.most_common(),
        top_signatures=signatures.most_common(top),
    )


def format_report(report: FrictionReport) -> list[str]:
    """Render the report as terminal lines."""
    if report.is_empty:
        return [
            "No permission denials recorded.",
            "",
            "That means none were LOGGED, not that none happened: ask-rule",
            "hits and no-match prompts reach no hook and are unmeasurable",
            "here (GH-1406). Check `dev10x permission catalog-gap` for the",
            "rules that WOULD prompt in this checkout.",
        ]

    lines = [f"Permission denials recorded: {report.total}", ""]
    lines.append("By rule family:")
    for family, count in report.by_family:
        share = 100 * count / report.total
        lines.append(f"  {count:>5}  ({share:5.1f}%)  {family}")

    if report.top_signatures:
        lines.extend(["", "Most-denied tool signatures:"])
        for signature, count in report.top_signatures:
            lines.append(f"  {count:>5}  {signature}")

    if report.unattributed:
        lines.extend(
            [
                "",
                f"{report.unattributed} record(s) predate GH-1406 and carry no tool",
                "signature. They are counted in the total but cannot be ranked.",
            ]
        )

    lines.extend(
        [
            "",
            "Denials only. A prompt from an ask rule or from no rule matching",
            "reaches no hook, so it is absent here by construction — this is a",
            "floor on observed friction, not a census of it.",
        ]
    )
    return lines
