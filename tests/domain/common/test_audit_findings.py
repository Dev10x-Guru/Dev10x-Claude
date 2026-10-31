"""Tests for permission-auditor finding parsing (GH-1631)."""

from __future__ import annotations

from typing import Any

import pytest
from dev10x.domain.common.audit_findings import (
    AuditFinding,
    FixAction,
    RuleList,
    Severity,
    parse_findings,
    select_findings,
)
from dev10x.domain.common.result import ErrorResult, SuccessResult


def _finding(**overrides: Any) -> dict[str, Any]:
    finding: dict[str, Any] = {
        "id": "F1",
        "title": "Broad rm allow",
        "severity": "HIGH",
        "file": "~/.claude/settings.local.json",
        "line": 12,
        "current_rule": "Bash(rm:*)",
        "proposed_fix": {
            "action": "replace",
            "list": "allow",
            "rule": "Bash(rm:*)",
            "replacement": "Bash(rm /tmp/Dev10x/:*)",
            "note": "narrow to the scratch root",
        },
        "rationale": "rm -rf on any path runs without a prompt",
    }
    finding.update(overrides)
    return finding


def _parse(*findings: dict[str, Any]) -> tuple[AuditFinding, ...]:
    result = parse_findings(payload={"findings": list(findings)})
    assert isinstance(result, SuccessResult)
    return result.value


def _error(payload: object) -> str:
    result = parse_findings(payload=payload)
    assert isinstance(result, ErrorResult)
    return result.error


class TestParseFindings:
    def test_parses_a_replace_fix(self) -> None:
        (finding,) = _parse(_finding())

        assert finding.severity is Severity.HIGH
        assert finding.proposed_fix.action is FixAction.REPLACE
        assert finding.proposed_fix.rule_list is RuleList.ALLOW
        assert finding.proposed_fix.replacement == "Bash(rm /tmp/Dev10x/:*)"

    def test_accepts_lowercase_severity(self) -> None:
        (finding,) = _parse(_finding(severity="critical"))

        assert finding.severity is Severity.CRITICAL

    def test_manual_fix_needs_no_rule(self) -> None:
        (finding,) = _parse(
            _finding(proposed_fix={"action": "manual", "note": "register the hook"})
        )

        assert finding.proposed_fix.action is FixAction.MANUAL
        assert finding.proposed_fix.rule_list is None

    def test_null_line_and_current_rule_are_allowed(self) -> None:
        (finding,) = _parse(_finding(line=None, current_rule=None))

        assert finding.line is None
        assert finding.current_rule is None

    def test_round_trips_to_wire_shape(self) -> None:
        (finding,) = _parse(_finding())

        data = finding.to_dict()

        assert data["proposed_fix"]["list"] == "allow"
        assert "rule_list" not in data["proposed_fix"]
        assert data["severity"] == "HIGH"

    def test_empty_list_is_valid(self) -> None:
        assert _parse() == ()

    @pytest.mark.parametrize(
        ("payload", "message"),
        [
            ([], "'findings' list"),
            ({"findings": "nope"}, "'findings' list"),
            ({"findings": ["nope"]}, "must be an object"),
            ({"findings": [_finding(id="")]}, "'id' must be a non-empty string"),
            ({"findings": [_finding(severity="URGENT")]}, "severity must be"),
            ({"findings": [_finding(line="12")]}, "'line' must be an integer"),
            ({"findings": [_finding(line=True)]}, "'line' must be an integer"),
            ({"findings": [_finding(current_rule=3)]}, "'current_rule' must be a string"),
            ({"findings": [_finding(proposed_fix="drop it")]}, "must be an object"),
            (
                {"findings": [_finding(proposed_fix={"action": "delete"})]},
                "proposed_fix.action must be one of",
            ),
            (
                {"findings": [_finding(proposed_fix={"action": "add", "list": "maybe"})]},
                "proposed_fix.list must be",
            ),
            (
                {"findings": [_finding(proposed_fix={"action": "add", "list": "deny"})]},
                "needs 'list' and 'rule'",
            ),
            (
                {
                    "findings": [
                        _finding(proposed_fix={"action": "replace", "list": "allow", "rule": "X"})
                    ]
                },
                "needs 'replacement'",
            ),
            (
                {"findings": [_finding(proposed_fix={"action": "manual", "note": 5})]},
                "'note' must be a string",
            ),
            ({"findings": [_finding(), _finding()]}, "duplicate id 'F1'"),
        ],
    )
    def test_rejects_malformed_block(self, payload: object, message: str) -> None:
        assert message in _error(payload)


class TestSelectFindings:
    @pytest.fixture
    def findings(self) -> tuple[AuditFinding, ...]:
        return _parse(
            _finding(id="low", severity="LOW"),
            _finding(id="crit", severity="CRITICAL"),
            _finding(id="med", severity="MEDIUM"),
            _finding(id="high", severity="HIGH"),
        )

    def test_no_ceiling_keeps_all_most_severe_first(
        self, findings: tuple[AuditFinding, ...]
    ) -> None:
        selection = select_findings(findings=findings, severity_max=None)

        assert [f.id for f in selection.selected] == ["crit", "high", "med", "low"]
        assert selection.excluded_by_severity == ()

    def test_high_ceiling_excludes_medium_and_low(
        self, findings: tuple[AuditFinding, ...]
    ) -> None:
        selection = select_findings(findings=findings, severity_max=Severity.HIGH)

        assert [f.id for f in selection.selected] == ["crit", "high"]
        assert [f.id for f in selection.excluded_by_severity] == ["med", "low"]
