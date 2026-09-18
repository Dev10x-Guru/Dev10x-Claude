"""Ranking recorded permission denials (GH-1406).

`build_report` is pure over its records so the ranking is testable
without an audit log — the CLI owns reading the log.
"""

from __future__ import annotations

import pytest

from dev10x.skills.permission.friction_report import (
    UNATTRIBUTED,
    build_report,
    format_report,
)


def _denial(signature: str | None = None, *, family: str | None = None) -> dict:
    record: dict = {"hook": "permission-denied", "phase": "body"}
    if signature is not None:
        record["tool_signature"] = signature
    if family is not None:
        record["rule_family"] = family
    return record


class TestBuildReport:
    def test_no_records_is_empty(self) -> None:
        assert build_report(records=[]).is_empty

    def test_ignores_other_hooks(self) -> None:
        records = [{"hook": "validate-bash", "tool_signature": "Bash(ls)"}]
        assert build_report(records=records).is_empty

    def test_counts_by_family(self) -> None:
        records = [
            _denial("Bash(gh pr view)", family="gh"),
            _denial("Bash(gh pr list)", family="gh"),
            _denial("Read(/etc/hosts)", family="read"),
        ]
        report = build_report(records=records)
        assert report.total == 3
        assert report.by_family == [("gh", 2), ("read", 1)]

    def test_ranks_signatures_most_frequent_first(self) -> None:
        records = [_denial("Bash(gh pr view)")] * 3 + [_denial("Read(/etc/hosts)")]
        report = build_report(records=records)
        assert report.top_signatures[0] == ("Bash(gh pr view)", 3)

    def test_top_limits_the_signature_list(self) -> None:
        records = [_denial(f"Bash(cmd{n})") for n in range(20)]
        assert len(build_report(records=records, top=5).top_signatures) == 5

    def test_derives_family_when_the_record_lacks_one(self) -> None:
        # A hook that recorded a signature but not yet a family still ranks.
        report = build_report(records=[_denial("mcp__plugin_Dev10x_cli__pr_get")])
        assert report.by_family == [("mcp", 1)]

    def test_recorded_family_wins_over_recomputation(self) -> None:
        # History must not be reclassified by a later change to
        # `rule_family` — the hook classified the live signature.
        report = build_report(records=[_denial("Bash(gh pr view)", family="legacy-family")])
        assert report.by_family == [("legacy-family", 1)]

    def test_pre_gh1406_records_are_counted_not_dropped(self) -> None:
        # Dropping them would understate friction on exactly the machines
        # with the longest history.
        report = build_report(records=[_denial(), _denial("Bash(gh pr view)", family="gh")])
        assert report.total == 2
        assert report.unattributed == 1
        assert report.attributed == 1
        assert (UNATTRIBUTED, 1) in report.by_family

    @pytest.mark.parametrize("signature", ["", None])
    def test_blank_signature_reads_as_unattributed(self, signature: str | None) -> None:
        assert build_report(records=[_denial(signature)]).unattributed == 1


class TestFormatReport:
    def test_empty_report_says_unmeasured_not_frictionless(self) -> None:
        text = "\n".join(format_report(build_report(records=[])))
        assert "not that none happened" in text
        assert "catalog-gap" in text

    def test_lists_families_with_shares(self) -> None:
        records = [_denial("Bash(gh pr view)", family="gh")] * 2
        text = "\n".join(format_report(build_report(records=records)))
        assert "gh" in text
        assert "100.0%" in text

    def test_always_states_the_denials_only_caveat(self) -> None:
        records = [_denial("Bash(gh pr view)", family="gh")]
        text = "\n".join(format_report(build_report(records=records)))
        assert "floor on observed friction" in text
