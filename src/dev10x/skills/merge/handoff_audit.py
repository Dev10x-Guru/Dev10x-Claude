"""Audit a worker's pre-merge handoff report before trusting it (GH-1380).

GH-1093 lets an orchestrator accept Checks 1d / 5 / 6 from a worker
subagent's report instead of re-running them. That exception treats the
report as evidence, which holds only while a report of the gate having
run is coupled to the gate having run.

Two workers broke that coupling: each stalled before reaching the gate,
the orchestrator ran the nine checks and merged by hand, and both workers
then resumed, observed the merged PR, and narrated the checklist as their
own work. A skipped gate is visible — no merge happens, or the raw
command is blocked. A falsely *claimed* gate is invisible, and it is
invisible precisely in the summary a supervisor reads to decide whether
to trust the merge.

So the report is checked against a trace it cannot author. GitHub already
records when a PR merged; a set of checks measured at or after that
moment cannot be the gate that preceded it, whatever the prose says.
Nothing new has to be recorded for that comparison to be available — the
receipt already exists, it was simply never read back.

Pure decisions only. Reading the report, calling ``pr_get`` and printing
belong to ``main`` and the caller (``.claude/rules/hook-patterns.md``).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

# GH-1093's failure posture: a report older than this describes state that
# has had time to drift, so the orchestrator re-runs everything.
MAX_REPORT_AGE = timedelta(minutes=30)

# A measurement cannot postdate the moment it is read back. Anything
# beyond ordinary clock skew between the worker's host and this one is a
# timestamp that was written rather than observed.
MAX_CLOCK_SKEW = timedelta(minutes=2)

REQUIRED_FIELDS = (
    "pr",
    "head_sha",
    "measured_at",
    "checks",
    "blocked_gate",
    "blocked_evidence",
)

# Words that assert a check passed without naming what was seen. `true`
# and `false` are deliberately absent: they are the observed values of
# `mergeable` and `isDraft`, not ticks.
_TICK_WORDS = frozenset(
    {
        "✓",
        "✔",
        "✅",
        "x",
        "ok",
        "okay",
        "pass",
        "passed",
        "passing",
        "good",
        "fine",
        "done",
        "yes",
        "clean",
        "n/a",
        "na",
        "none",
    }
)

_CHECKLIST_MARKUP = ("- [x]", "- [X]", "[x]", "[X]", "-", "*", "✓", "✔", "✅")

ACCEPT = "accept"
REJECT = "reject"
ALREADY_MERGED = "already_merged"


@dataclass(frozen=True)
class HandoffAudit:
    """Whether a worker's report may stand in for re-running the checks."""

    verdict: str
    reasons: tuple[str, ...] = ()
    merged_at: str | None = None
    merged_by: str | None = None

    @property
    def accepted(self) -> bool:
        return self.verdict == ACCEPT

    def summary(self) -> str:
        if self.accepted:
            return "report accepted — Checks 1d/5/6 may be inherited"
        if self.verdict == ALREADY_MERGED:
            actor = self.merged_by or "an actor the PR state does not name"
            return f"PR already merged by {actor}; the report did not gate this merge"
        return "; ".join(self.reasons) or "report rejected"


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _strip_markup(entry: str) -> str:
    text = entry.strip()
    for marker in _CHECKLIST_MARKUP:
        if text.startswith(marker):
            text = text[len(marker) :].strip()
    return text


def names_observed_value(entry: object) -> bool:
    """Does one checklist entry name the value its verdict was read from?

    A bare tick is the shortcut GH-112 caught and GH-1380 is the reason it
    has to be machine-checked: prose that narrates the pipeline reads
    exactly like prose that reports it, until you ask each line what it
    saw.
    """
    if isinstance(entry, Mapping):
        observed = entry.get("observed")
        return isinstance(observed, str) and _is_measurement(observed.strip())
    if not isinstance(entry, str):
        return False
    text = _strip_markup(entry)
    _, separator, value = text.rpartition(":")
    if not separator:
        return False
    return _is_measurement(value.strip())


def _is_measurement(value: str) -> bool:
    return bool(value) and value.strip().strip(".").lower() not in _TICK_WORDS


def _missing_fields(report: Mapping[str, object]) -> tuple[str, ...]:
    return tuple(field for field in REQUIRED_FIELDS if not report.get(field))


def _is_merged(pr_state: Mapping[str, object]) -> bool:
    state = pr_state.get("state")
    merged_state = isinstance(state, str) and state.strip().upper() == "MERGED"
    return merged_state or bool(pr_state.get("mergedAt")) or bool(pr_state.get("merged"))


def _merged_by(pr_state: Mapping[str, object]) -> str | None:
    """Who merged, when the PR state happens to name them.

    ``pr_get`` carries ``mergedAt`` but no merging actor, while
    ``merge_pr`` reports ``merged_as`` (GH-1272). Attribution is therefore
    reported when it is available and never fabricated when it is not —
    the timing alone already settles whether the report gated the merge.
    """
    for key in ("mergedBy", "merged_by", "merged_as"):
        value = pr_state.get(key)
        if isinstance(value, Mapping):
            value = value.get("login")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _already_merged_audit(
    *,
    report: Mapping[str, object],
    pr_state: Mapping[str, object],
) -> HandoffAudit:
    merged_at_raw = pr_state.get("mergedAt")
    merged_at = _parse_timestamp(merged_at_raw)
    measured_at = _parse_timestamp(report.get("measured_at"))
    reasons = ["PR is already merged — a handoff report cannot authorize a merge that happened"]
    if merged_at and measured_at and measured_at >= merged_at:
        reasons.append(
            f"report measured at {measured_at.isoformat()} does not precede the merge at"
            f" {merged_at.isoformat()} — these checks did not gate it"
        )
    return HandoffAudit(
        verdict=ALREADY_MERGED,
        reasons=tuple(reasons),
        merged_at=merged_at_raw if isinstance(merged_at_raw, str) else None,
        merged_by=_merged_by(pr_state),
    )


def audit_handoff_report(
    *,
    report: Mapping[str, object],
    pr_state: Mapping[str, object],
    now: datetime | None = None,
) -> HandoffAudit:
    """Decide whether ``report`` may stand in for re-running Checks 1d/5/6.

    ``already_merged`` is separated from ``reject`` deliberately. A merged
    PR is not a malformed report — it is a report that describes someone
    else's work, and the orchestrator's correct response is to attribute
    the merge rather than to ask the worker for a better report.
    """
    if _is_merged(pr_state):
        return _already_merged_audit(report=report, pr_state=pr_state)

    moment = now or datetime.now(UTC)
    reasons: list[str] = []

    missing = _missing_fields(report)
    if missing:
        reasons.append(f"missing required field(s): {', '.join(missing)}")

    checks = report.get("checks")
    if isinstance(checks, Mapping):
        entries: Sequence[object] = list(checks.values())
    elif isinstance(checks, Sequence) and not isinstance(checks, str):
        entries = checks
    else:
        entries = ()
        if "checks" not in missing:
            reasons.append("checks is not a list or mapping of per-check entries")
    unverifiable = [entry for entry in entries if not names_observed_value(entry)]
    if unverifiable:
        reasons.append(
            f"{len(unverifiable)} check(s) name no observed value — a bare tick is not evidence"
        )

    head_sha = report.get("head_sha")
    live_sha = pr_state.get("headRefOid")
    if head_sha and live_sha and str(head_sha) != str(live_sha):
        reasons.append(f"head SHA moved: report {head_sha}, PR {live_sha}")

    measured_at = _parse_timestamp(report.get("measured_at"))
    if report.get("measured_at") and measured_at is None:
        reasons.append("measured_at is not an ISO-8601 timestamp")
    elif measured_at is not None:
        if moment - measured_at > MAX_REPORT_AGE:
            reasons.append(f"report is older than {int(MAX_REPORT_AGE.total_seconds() // 60)}m")
        elif measured_at - moment > MAX_CLOCK_SKEW:
            reasons.append("measured_at is in the future — it was written, not observed")

    if reasons:
        return HandoffAudit(verdict=REJECT, reasons=tuple(reasons))
    return HandoffAudit(verdict=ACCEPT)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit a subagent's pre-merge handoff report (GH-1380)."
    )
    parser.add_argument("--report-file", required=True, help="file holding the report JSON")
    parser.add_argument(
        "--pr-state-file",
        required=True,
        help="file holding a fresh pr_get response as JSON",
    )
    args = parser.parse_args(argv)

    # stdout is the single channel: this script's output is parsed, so an
    # error on stderr with empty stdout would leave the caller with nothing
    # to read (script-domain-boundaries.md).
    try:
        report = json.loads(Path(args.report_file).read_text(encoding="utf-8"))
        pr_state = json.loads(Path(args.pr_state_file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    if not isinstance(report, Mapping) or not isinstance(pr_state, Mapping):
        print(json.dumps({"error": "both files must hold a JSON object"}))
        return 2

    audit = audit_handoff_report(report=report, pr_state=pr_state)
    print(
        json.dumps(
            {
                "verdict": audit.verdict,
                "accepted": audit.accepted,
                "reasons": list(audit.reasons),
                "merged_at": audit.merged_at,
                "merged_by": audit.merged_by,
                "summary": audit.summary(),
            },
            indent=2,
        )
    )
    return 0 if audit.accepted else 1


if __name__ == "__main__":  # pragma: no cover - exercised via the shim
    sys.exit(main())
