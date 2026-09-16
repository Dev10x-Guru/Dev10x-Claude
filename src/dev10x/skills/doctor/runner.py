"""Non-interactive plugin-doctor sweep (GH-1321).

``Dev10x:plugin-doctor`` is Claude-orchestrated only, so catalog health
is assertable exactly when a human is present to assert it. That is how
GH-1100's redundant-rule drift survived for months: the only detector
was somebody noticing a prompt.

This module is the same sweep with no agent in the loop. It runs the
registered strategies over a :class:`Context`, partitions the findings
against the acceptance catalog, and returns a structured payload. It
prints nothing and exits nothing — :mod:`dev10x.commands.doctor` owns
stdout and the exit code, per ``.claude/rules/script-domain-boundaries.md``.

**Severity is the noise gate, and acceptance is the second one.**
Running a detector unattended multiplies whatever its false-positive
rate is, so the runner must not treat every finding as a failure. Two
mechanisms keep it honest, in this order:

1. ``threshold`` — only findings at or above it are ``blocking``.
   Default ``drift``, which excludes ``suggestion``. The doctor's
   largest known false-positive class (``ask-shadows-allow``'s narrowing
   shape, 69 of 73 findings in the 2026-09-07 audit) is graded
   ``suggestion`` precisely so it never gates anything.
2. ``accepted`` — durable per-(strategy, location) answers from the
   maintainer. Accepted findings are still detected, still returned, and
   still counted; they are simply not blocking.

``stale_acceptances`` closes the loop the other way. An entry matching
nothing this run is reported so the catalog cannot silently accumulate
suppressions for drift that no longer exists — the same discipline
:func:`dev10x.skills.permission.baseline_coverage.triaged_backlog`
applies to its ratchet.
"""

from __future__ import annotations

import logging
from typing import Any

from dev10x.domain.common.doctor_acceptance import (
    AcceptedDoctorFinding,
    find_doctor_acceptance,
)
from dev10x.domain.common.result import Result, err, ok
from dev10x.skills.doctor.registry import load_strategies
from dev10x.skills.doctor.strategy import Context, Finding, Severity, StrategyProtocol

log = logging.getLogger(__name__)

#: Least to most severe. Index order is the comparison.
SEVERITY_ORDER: tuple[Severity, ...] = ("suggestion", "drift", "critical")

DEFAULT_THRESHOLD: Severity = "drift"


def _rank(severity: str) -> int:
    """Where ``severity`` sits on the scale; unknown values rank lowest.

    An unrecognised grade from a user strategy must not become the most
    severe thing in the run by accident, so it sorts with suggestions
    rather than raising — the run still reports it.
    """
    try:
        return SEVERITY_ORDER.index(severity)  # type: ignore[arg-type]
    except ValueError:
        log.warning("Unknown severity %r; ranking it as the lowest grade", severity)
        return 0


def _rendered(finding: Finding) -> dict[str, Any]:
    return {
        "strategy_id": finding.strategy_id,
        "severity": finding.severity,
        "location": finding.location,
        "evidence": finding.evidence,
        "proposed_fix": finding.proposed_fix,
    }


def _detect_all(*, strategies: list[StrategyProtocol], context: Context) -> list[Finding]:
    """Every strategy's findings, or a raised error naming the culprit.

    A strategy that raises is a defect, not drift, and a run that
    silently drops it would report better health than the machine has.
    The caller turns the exception into an ``ErrorResult``.
    """
    findings: list[Finding] = []
    for strategy in strategies:
        try:
            findings.extend(strategy.detect(context))
        except Exception as exc:  # noqa: BLE001 — re-raised with attribution below
            raise DoctorStrategyError(strategy_id=strategy.id, cause=exc) from exc
    return findings


class DoctorStrategyError(Exception):
    """A registered strategy raised during ``detect``."""

    def __init__(self, *, strategy_id: str, cause: Exception) -> None:
        super().__init__(f"strategy {strategy_id!r} failed: {cause}")
        self.strategy_id = strategy_id


def run_doctor(
    *,
    context: Context,
    accepted: tuple[AcceptedDoctorFinding, ...] = (),
    threshold: Severity = DEFAULT_THRESHOLD,
    strategies: list[StrategyProtocol] | None = None,
) -> Result[dict[str, Any]]:
    """Sweep every strategy and partition the findings for a CI caller."""
    loaded = load_strategies() if strategies is None else strategies
    try:
        findings = _detect_all(strategies=loaded, context=context)
    except DoctorStrategyError as exc:
        return err(str(exc), strategy_id=exc.strategy_id)

    reported: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    used: set[tuple[str, str]] = set()
    for finding in findings:
        acceptance = find_doctor_acceptance(
            strategy=finding.strategy_id,
            location=finding.location,
            catalog=accepted,
        )
        if acceptance is None:
            reported.append(_rendered(finding))
            continue
        used.add((acceptance.strategy, acceptance.location))
        suppressed.append(
            _rendered(finding) | {"rationale": acceptance.rationale, "source": acceptance.source}
        )

    floor = _rank(threshold)
    blocking = [entry for entry in reported if _rank(entry["severity"]) >= floor]
    return ok(
        {
            "findings": reported,
            "accepted": suppressed,
            "stale_acceptances": [
                {"strategy": entry.strategy, "location": entry.location, "source": entry.source}
                for entry in accepted
                if (entry.strategy, entry.location) not in used
            ],
            "counts": _counts(reported=reported, suppressed=suppressed),
            "threshold": threshold,
            "blocking": len(blocking),
            "strategies_run": [strategy.id for strategy in loaded],
        }
    )


def _counts(
    *,
    reported: list[dict[str, Any]],
    suppressed: list[dict[str, Any]],
) -> dict[str, int]:
    counts: dict[str, int] = {severity: 0 for severity in SEVERITY_ORDER}
    for entry in reported:
        severity = entry["severity"]
        counts[severity] = counts.get(severity, 0) + 1
    counts["accepted"] = len(suppressed)
    return counts


__all__ = [
    "DEFAULT_THRESHOLD",
    "SEVERITY_ORDER",
    "DoctorStrategyError",
    "run_doctor",
]
