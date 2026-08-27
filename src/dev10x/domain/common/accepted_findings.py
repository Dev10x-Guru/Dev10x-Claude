"""Accepted-by-design auditor findings (GH-1053, GH-1067).

Some allow rules look alarming to a shape-only classifier yet are
deliberate, supervisor-ratified policy. ``Bash(git reset --hard:*)`` is
the worked example: the baseline catalog ships it *and* the broader
``Bash(git reset:*)``, so
:func:`dev10x.skills.permission.policy_audit._is_redundant` reports the
explicit variant as REDUNDANT and proposes removing it — the very rule
``ensure-base`` re-adds on the next maintenance run. Step 4 and step 10
of ``Dev10x:plugin-maintenance`` then fight each other on every pass.

An acceptance is therefore a *durable answer* to a finding, not a
weakening of the audit: the finding is still computed, still counted,
and still shown — under a "suppressed by accepted-findings" heading —
but it is no longer proposed as a change. Matching is pure so both the
shipped catalog and the user overlay share one code path; file I/O
lives in :mod:`dev10x.skills.permission.accepted_findings`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SHIPPED_SOURCE = "shipped"


@dataclass(frozen=True)
class AcceptedFinding:
    """One rule shape whose audit findings the maintainer has ratified.

    ``classifications`` empty means "every finding on this rule". Naming
    tokens instead keeps an acceptance narrow: accepting the REDUNDANT
    verdict on ``Bash(git push --force:*)`` must not also silence a
    future WILDCARD_ESCAPE verdict on the same rule.
    """

    rule: str
    rationale: str
    classifications: frozenset[str] = field(default_factory=frozenset)
    source: str = SHIPPED_SOURCE

    def covers(self, *, rule: str, classification: str) -> bool:
        if self.rule != rule:
            return False
        return not self.classifications or classification in self.classifications


_REDUNDANT = frozenset({"REDUNDANT"})

# The shipped set is deliberately small and each entry names the ruling
# that put it here. Recoverability is the shared test: every operation
# below removes a ref or moves a pointer, and `git log -g` restores it.
# History *removal* is not on this list, and neither is a protected-branch
# force-push — `push_safe` (GH-1031) rails that at the wrapper layer.
DEFAULT_ACCEPTED_FINDINGS: tuple[AcceptedFinding, ...] = (
    AcceptedFinding(
        rule="Bash(git reset --hard:*)",
        classifications=_REDUNDANT,
        rationale=(
            "GH-1053: daily workflow in a fixup-heavy groom/rebase cycle and "
            "reflog-recoverable. Shipped by the baseline catalog alongside the "
            "broader Bash(git reset:*), so 'remove the subsumed rule' would "
            "undo what ensure-base re-adds on the next run."
        ),
    ),
    AcceptedFinding(
        rule="Bash(git push --force:*)",
        classifications=_REDUNDANT,
        rationale=(
            "GH-1053: protected-branch force-pushes are railed by push_safe "
            "(GH-1031) at the wrapper layer; a permission-layer gate would "
            "duplicate that guard and prompt on every routine groom."
        ),
    ),
    AcceptedFinding(
        rule="Bash(git push -f:*)",
        classifications=_REDUNDANT,
        rationale="GH-1053: short spelling of Bash(git push --force:*) — same ruling.",
    ),
    AcceptedFinding(
        rule="Bash(git branch -D:*)",
        classifications=_REDUNDANT,
        rationale=(
            "GH-1067: deleting a local branch removes a ref, not history — the "
            "tip stays reachable via git log -g. Unattended cleanup after killed "
            "workers must not wedge on a prompt no one is present to answer."
        ),
    ),
    AcceptedFinding(
        rule="Bash(git branch -d:*)",
        classifications=_REDUNDANT,
        rationale="GH-1067: safe spelling of the branch-deletion family — same ruling.",
    ),
    AcceptedFinding(
        rule="Bash(git branch --delete:*)",
        classifications=_REDUNDANT,
        rationale="GH-1067: long spelling of the branch-deletion family — same ruling.",
    ),
)


def find_acceptance(
    *,
    rule: str,
    classification: str,
    catalog: tuple[AcceptedFinding, ...],
) -> AcceptedFinding | None:
    """First catalog entry covering this (rule, classification), if any.

    Catalog order decides, so a user overlay entry placed ahead of the
    shipped set can restate a rationale in the maintainer's own words.
    """
    for entry in catalog:
        if entry.covers(rule=rule, classification=classification):
            return entry
    return None


__all__ = [
    "DEFAULT_ACCEPTED_FINDINGS",
    "SHIPPED_SOURCE",
    "AcceptedFinding",
    "find_acceptance",
]
