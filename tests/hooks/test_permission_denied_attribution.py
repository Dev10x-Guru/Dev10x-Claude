"""The PermissionDenied record names the tool that was denied (GH-1406).

Before this, the record carried only wrap-phase timing, so the audit log
could say a prompt happened but never which tool caused it — which is
why every friction tracker in this repo was typed up by hand from a
terminal. These tests pin the two fields a report aggregates on.
"""

from __future__ import annotations

import logging
from typing import Never

import pytest

from dev10x.commands.hook import _record_denied_tool, _run_permission_diagnostics
from dev10x.hooks import audit_emit
from dev10x.hooks.permission_diagnostics import DiagnosticResult


def _raise_boom(*args: object, **kwargs: object) -> Never:
    raise RuntimeError("boom")


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


class TestDiagnosticsFailureLeavesATrace:
    """A broken diagnostic must not fail silently (GH-1418).

    The traceback used to be gated behind ``HOOK_DEBUG``, so outside
    debug mode a raised exception left nothing anywhere. These pin the
    two channels that make it discoverable, and the guard that keeps
    the recording itself from raising inside an exception handler.
    """

    @pytest.fixture(autouse=True)
    def _a_diagnostic_that_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Every test here needs the same non-debug, raising baseline."""
        monkeypatch.delenv("HOOK_DEBUG", raising=False)
        monkeypatch.setattr(
            "dev10x.hooks.permission_diagnostics.diagnose",
            _raise_boom,
        )

    def test_a_raising_diagnostic_is_recorded_in_the_audit_slot(self) -> None:
        _run_permission_diagnostics(raw={}, cwd="/tmp")

        assert _slot()["rule_id"] == "permission-diagnostics-failed"

    def test_a_raising_diagnostic_is_logged_with_a_traceback(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="dev10x.commands.hook"):
            _run_permission_diagnostics(raw={}, cwd="/tmp")

        record = next(r for r in caplog.records if "diagnostic degraded" in r.message)
        assert record.levelno == logging.WARNING, (
            "must be at or above the default threshold — logging at debug "
            "would reproduce the silence GH-1418 fixes"
        )
        assert record.exc_info is not None, "exc_info=True is what makes it diagnosable"

    def test_the_hook_survives_a_failure_to_record(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Recording runs inside an exception handler; raising there
        would propagate into the hook's own exit path."""
        monkeypatch.delenv("HOOK_DEBUG", raising=False)
        monkeypatch.setattr(
            "dev10x.hooks.permission_diagnostics.diagnose",
            _raise_boom,
        )
        monkeypatch.setattr(
            audit_emit,
            "set_decision_attribution",
            _raise_boom,
        )

        _run_permission_diagnostics(raw={}, cwd="/tmp")
