"""The PermissionDenied record names the tool that was denied (GH-1406).

Before this, the record carried only wrap-phase timing, so the audit log
could say a prompt happened but never which tool caused it — which is
why every friction tracker in this repo was typed up by hand from a
terminal. These tests pin the two fields a report aggregates on.
"""

from __future__ import annotations

import pytest

from dev10x.commands.hook import _record_denied_tool
from dev10x.hooks import audit_emit
from dev10x.hooks.permission_diagnostics import DiagnosticResult


@pytest.fixture(autouse=True)
def _clear_slot() -> None:
    # The attribution slot is module-level state consumed by the next
    # record written; tests reuse one process.
    audit_emit.clear_decision_attribution()


def _result(signature: str) -> DiagnosticResult:
    return DiagnosticResult(
        tool_signature=signature,
        matches=[],
        diagnosis="No matching allow rule found in any settings file.",
        fix_suggestion="",
    )


def _slot() -> dict[str, str]:
    return audit_emit._decision_attribution or {}


def test_records_the_tool_signature() -> None:
    _record_denied_tool(result=_result("Bash(gh pr view 42)"))
    assert _slot()["tool_signature"] == "Bash(gh pr view 42)"


def test_records_the_diagnosis_as_the_reason() -> None:
    _record_denied_tool(result=_result("Bash(gh pr view 42)"))
    assert "No matching allow rule" in _slot()["reason"]


@pytest.mark.parametrize(
    ("signature", "family"),
    [
        ("Bash(gh pr view 42)", "gh"),
        ("Bash(git status)", "git"),
        ("mcp__plugin_Dev10x_cli__pr_get", "mcp"),
        ("Read(/etc/hosts)", "read"),
        ("Edit(/tmp/x)", "edit"),
    ],
)
def test_classifies_the_family_at_record_time(signature: str, family: str) -> None:
    # Classifying here rather than at read time is what keeps a later
    # change to `rule_family` from reclassifying recorded history.
    _record_denied_tool(result=_result(signature))
    assert _slot()["rule_family"] == family


def test_attribution_names_the_rule() -> None:
    _record_denied_tool(result=_result("Bash(gh pr view 42)"))
    assert _slot()["rule_id"] == "permission-denied"
