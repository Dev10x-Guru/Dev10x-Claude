"""Accepted-by-design plugin-doctor findings (GH-1321).

The doctor's counterpart to
:mod:`dev10x.domain.common.accepted_findings`, and it exists for the
same reason one release earlier: a detector that cannot be answered
re-asks forever. ``Dev10x:plugin-doctor``'s own SKILL.md names the
consequence in its anti-patterns — "a periodic run would re-prompt for
findings the user already chose to skip" — and that sentence is the
whole argument against a non-interactive runner until a durable answer
exists. So the answer ships first and the runner reads it.

An acceptance is a **durable answer**, not a filter. The finding is
still detected, still carried in the payload, and still counted; it is
moved out of the set that decides the exit code and rendered with the
rationale that retired it. Suppression that hides is how a baseline
rots into a place findings go to disappear.

Matching is pure so the shipped catalog and the user overlay share one
code path; file I/O lives in :mod:`dev10x.skills.doctor.acceptance`.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass

SHIPPED_SOURCE = "shipped"

#: An entry with no ``location`` accepts every finding its strategy
#: emits. That is the blunt instrument, and it is spelled as a glob
#: rather than a separate field so the narrow form is the shorter one.
ANY_LOCATION = "*"


@dataclass(frozen=True)
class AcceptedDoctorFinding:
    """One (strategy, location) pair whose findings the maintainer ratified.

    ``location`` is an ``fnmatch`` glob over the finding's location —
    usually a settings-file path — so one entry can cover the same
    settings file across every worktree of a repo without naming each.
    """

    strategy: str
    rationale: str
    location: str = ANY_LOCATION
    source: str = SHIPPED_SOURCE

    def covers(self, *, strategy: str, location: str) -> bool:
        if self.strategy != strategy:
            return False
        return fnmatch.fnmatch(name=location, pat=self.location)


#: Deliberately empty, and the emptiness is the position rather than an
#: oversight.
#:
#: The doctor's known false-positive mass is ``ask-shadows-allow``'s
#: narrowing shape — 69 of 73 findings in the 2026-09-07 audit were a
#: broad allow paired with an intentional narrow deny. GH-1222 already
#: answered that at the source by grading it ``suggestion``, and the
#: runner's default threshold does not block on suggestions. Shipping an
#: acceptance for it as well would be a second answer to a question
#: already settled, and would mask the day the same strategy reports a
#: genuinely contradictory duplicate.
#:
#: Everything else a maintainer wants to retire is machine-local by
#: nature — a finding's location is an absolute path on their box — so
#: it belongs in their overlay, not in a set shipped to every user.
DEFAULT_ACCEPTED_DOCTOR_FINDINGS: tuple[AcceptedDoctorFinding, ...] = ()


def find_doctor_acceptance(
    *,
    strategy: str,
    location: str,
    catalog: tuple[AcceptedDoctorFinding, ...],
) -> AcceptedDoctorFinding | None:
    """First catalog entry covering this (strategy, location), if any.

    Catalog order decides, so a user overlay entry placed ahead of the
    shipped set wins for the same strategy.
    """
    for entry in catalog:
        if entry.covers(strategy=strategy, location=location):
            return entry
    return None


__all__ = [
    "ANY_LOCATION",
    "DEFAULT_ACCEPTED_DOCTOR_FINDINGS",
    "SHIPPED_SOURCE",
    "AcceptedDoctorFinding",
    "find_doctor_acceptance",
]
