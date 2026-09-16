"""The handoff report is checked against a trace it cannot author (GH-1380).

Two workers reported running the nine-check gate for PRs the orchestrator
had merged by hand after both stalled. A skipped gate is visible; a
falsely claimed one is not. These pin the comparison that makes the claim
checkable: a set of checks measured at or after the merge cannot be the
gate that preceded it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from dev10x.skills.merge.handoff_audit import (
    ACCEPT,
    ALREADY_MERGED,
    REJECT,
    audit_handoff_report,
    main,
    names_observed_value,
)

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
HEAD = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"

GOOD_REPORT = {
    "pr": "Dev10x-Guru/Dev10x-Claude#1362",
    "head_sha": HEAD,
    "measured_at": "2026-09-16T11:55:00Z",
    "checks": [
        "Check 1 unresolved threads: 0",
        "Check 1b top-level findings: 0 blocking, 0 needing disposition",
        "Check 1c inline findings: 0",
        "Check 1d Fixes links: 1/1 backed",
        "Check 2 CI verdict: green",
        "Check 2b state: OPEN, autoMergeRequest: null",
        "Check 3 isDraft: false",
        "Check 4 mergeable: MERGEABLE",
        "Check 5 git status --porcelain: 0 lines",
        "Check 6 fixup commits: 0 of 4",
        "Check 7 reviewDecision: waived by solo_maintainer",
    ],
    "blocked_gate": "Check 2 infrastructure override",
    "blocked_evidence": "claude-review failed on 'Credit balance is too low'",
}

OPEN_PR = {"state": "OPEN", "headRefOid": HEAD, "mergedAt": None}


def report(**overrides: object) -> dict[str, object]:
    return {**GOOD_REPORT, **overrides}


class TestNamesObservedValue:
    @pytest.mark.parametrize(
        "entry",
        [
            "Check 3 isDraft: false",
            "- [x] mergeable: MERGEABLE",
            "✅ unresolved threads: 0",
            {"check": "5", "observed": "0 lines"},
        ],
    )
    def test_accepts_an_entry_naming_what_was_seen(self, entry):
        assert names_observed_value(entry) is True

    @pytest.mark.parametrize(
        "entry",
        [
            "Check 3: passed",
            "- [x] Working copy is clean: yes",
            "✓",
            "No merge conflicts",
            {"check": "5", "observed": "ok"},
            {"check": "5"},
            42,
        ],
    )
    def test_rejects_an_entry_that_only_asserts_success(self, entry):
        assert names_observed_value(entry) is False


class TestAcceptance:
    def test_accepts_a_complete_fresh_report_on_an_open_pr(self):
        audit = audit_handoff_report(report=report(), pr_state=OPEN_PR, now=NOW)
        assert audit.verdict == ACCEPT
        assert audit.accepted is True
        assert audit.summary() == "report accepted — Checks 1d/5/6 may be inherited"

    def test_accepts_checks_given_as_a_mapping(self):
        entries = {f"check{index}": value for index, value in enumerate(GOOD_REPORT["checks"])}
        audit = audit_handoff_report(report=report(checks=entries), pr_state=OPEN_PR, now=NOW)
        assert audit.verdict == ACCEPT

    def test_defaults_now_to_the_current_moment(self):
        fresh = report(measured_at=datetime.now(UTC).isoformat())
        assert audit_handoff_report(report=fresh, pr_state=OPEN_PR).verdict == ACCEPT


class TestAlreadyMerged:
    """The GH-1380 case: the report describes someone else's work."""

    def test_reports_already_merged_rather_than_accepting(self):
        merged = {
            "state": "MERGED",
            "headRefOid": HEAD,
            "mergedAt": "2026-09-16T11:50:00Z",
            "mergedBy": {"login": "orchestrator"},
        }
        audit = audit_handoff_report(report=report(), pr_state=merged, now=NOW)
        assert audit.verdict == ALREADY_MERGED
        assert audit.accepted is False
        assert audit.merged_by == "orchestrator"
        assert audit.merged_at == "2026-09-16T11:50:00Z"
        assert "does not precede the merge" in " ".join(audit.reasons)
        assert audit.summary() == (
            "PR already merged by orchestrator; the report did not gate this merge"
        )

    def test_names_no_actor_when_the_pr_state_carries_none(self):
        merged = {"state": "MERGED", "headRefOid": HEAD, "mergedAt": None}
        audit = audit_handoff_report(report=report(), pr_state=merged, now=NOW)
        assert audit.merged_by is None
        assert audit.merged_at is None
        assert "an actor the PR state does not name" in audit.summary()

    def test_reads_merged_as_when_that_is_the_only_attribution(self):
        merged = {"merged": True, "merged_as": "bot", "mergedAt": "2026-09-16T11:50:00Z"}
        assert audit_handoff_report(report=report(), pr_state=merged, now=NOW).merged_by == "bot"

    def test_omits_the_timing_reason_when_the_report_genuinely_preceded_the_merge(self):
        merged = {"state": "MERGED", "mergedAt": "2026-09-16T11:58:00Z"}
        audit = audit_handoff_report(report=report(), pr_state=merged, now=NOW)
        assert audit.verdict == ALREADY_MERGED
        assert "does not precede the merge" not in " ".join(audit.reasons)

    def test_a_malformed_report_on_a_merged_pr_is_still_already_merged(self):
        # Attribution, not "send a better report": the worker cannot fix a
        # merge that has happened.
        merged = {"state": "merged", "mergedAt": "2026-09-16T11:50:00Z"}
        audit = audit_handoff_report(report={}, pr_state=merged, now=NOW)
        assert audit.verdict == ALREADY_MERGED


class TestRejection:
    def test_names_every_missing_field(self):
        stripped = {key: value for key, value in GOOD_REPORT.items() if key != "blocked_gate"}
        audit = audit_handoff_report(report=stripped, pr_state=OPEN_PR, now=NOW)
        assert audit.verdict == REJECT
        assert "missing required field(s): blocked_gate" in audit.reasons

    def test_rejects_a_checklist_of_bare_ticks(self):
        audit = audit_handoff_report(
            report=report(checks=["Check 3: passed", "Check 4: ok"]),
            pr_state=OPEN_PR,
            now=NOW,
        )
        assert "2 check(s) name no observed value — a bare tick is not evidence" in audit.reasons

    def test_rejects_checks_given_as_prose(self):
        audit = audit_handoff_report(
            report=report(checks="I ran all nine and they passed"),
            pr_state=OPEN_PR,
            now=NOW,
        )
        assert "checks is not a list or mapping of per-check entries" in audit.reasons

    def test_does_not_double_report_an_absent_checks_field(self):
        audit = audit_handoff_report(report=report(checks=[]), pr_state=OPEN_PR, now=NOW)
        assert audit.reasons == ("missing required field(s): checks",)

    def test_rejects_a_moved_head_sha(self):
        moved = {**OPEN_PR, "headRefOid": "0" * 40}
        audit = audit_handoff_report(report=report(), pr_state=moved, now=NOW)
        assert audit.verdict == REJECT
        assert any("head SHA moved" in reason for reason in audit.reasons)

    def test_rejects_a_report_older_than_thirty_minutes(self):
        stale = report(measured_at=(NOW - timedelta(minutes=31)).isoformat())
        audit = audit_handoff_report(report=stale, pr_state=OPEN_PR, now=NOW)
        assert "report is older than 30m" in audit.reasons

    def test_rejects_a_measurement_dated_in_the_future(self):
        ahead = report(measured_at=(NOW + timedelta(minutes=10)).isoformat())
        audit = audit_handoff_report(report=ahead, pr_state=OPEN_PR, now=NOW)
        assert "measured_at is in the future — it was written, not observed" in audit.reasons

    def test_tolerates_ordinary_clock_skew(self):
        skewed = report(measured_at=(NOW + timedelta(seconds=30)).isoformat())
        assert audit_handoff_report(report=skewed, pr_state=OPEN_PR, now=NOW).verdict == ACCEPT

    def test_accepts_a_naive_timestamp_as_utc(self):
        naive = report(measured_at="2026-09-16T11:55:00")
        assert audit_handoff_report(report=naive, pr_state=OPEN_PR, now=NOW).verdict == ACCEPT

    def test_rejects_an_unparseable_timestamp(self):
        audit = audit_handoff_report(
            report=report(measured_at="just now"), pr_state=OPEN_PR, now=NOW
        )
        assert "measured_at is not an ISO-8601 timestamp" in audit.reasons

    def test_summary_falls_back_when_a_rejection_carries_no_reason(self):
        from dev10x.skills.merge.handoff_audit import HandoffAudit

        assert HandoffAudit(verdict=REJECT).summary() == "report rejected"


class TestMain:
    def _write(self, tmp_path, name, payload):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    def test_exits_zero_and_prints_the_verdict_on_acceptance(self, tmp_path, capsys):
        # `main` reads the real clock, so the report has to be genuinely fresh.
        fresh = report(measured_at=datetime.now(UTC).isoformat())
        code = main(
            [
                "--report-file",
                self._write(tmp_path, "report.json", fresh),
                "--pr-state-file",
                self._write(tmp_path, "pr.json", OPEN_PR),
            ]
        )
        printed = json.loads(capsys.readouterr().out)
        assert code == 0
        assert printed["verdict"] == ACCEPT
        assert printed["accepted"] is True

    def test_exits_non_zero_when_the_pr_is_already_merged(self, tmp_path, capsys):
        merged = {"state": "MERGED", "mergedAt": "2026-09-16T11:50:00Z", "mergedBy": "janusz"}
        code = main(
            [
                "--report-file",
                self._write(tmp_path, "report.json", GOOD_REPORT),
                "--pr-state-file",
                self._write(tmp_path, "pr.json", merged),
            ]
        )
        printed = json.loads(capsys.readouterr().out)
        assert code == 1
        assert printed["verdict"] == ALREADY_MERGED
        assert printed["merged_by"] == "janusz"

    def test_reports_an_unreadable_file_on_stdout(self, tmp_path, capsys):
        code = main(
            [
                "--report-file",
                str(tmp_path / "absent.json"),
                "--pr-state-file",
                self._write(tmp_path, "pr.json", OPEN_PR),
            ]
        )
        assert code == 2
        assert "error" in json.loads(capsys.readouterr().out)

    def test_refuses_a_file_that_does_not_hold_an_object(self, tmp_path, capsys):
        code = main(
            [
                "--report-file",
                self._write(tmp_path, "report.json", ["not", "an", "object"]),
                "--pr-state-file",
                self._write(tmp_path, "pr.json", OPEN_PR),
            ]
        )
        assert code == 2
        assert json.loads(capsys.readouterr().out)["error"] == "both files must hold a JSON object"
