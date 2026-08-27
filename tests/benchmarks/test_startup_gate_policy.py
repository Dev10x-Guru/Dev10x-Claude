"""Tests for the CI-enforced / locally-advisory timing gate (GH-1080)."""

from __future__ import annotations

import warnings

import pytest

from tests.benchmarks.test_startup_time import (
    STRICT_ENV,
    _report_timing,
    timing_gate_is_enforced,
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neither flag set — the plain developer-laptop case."""
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv(STRICT_ENV, raising=False)


class TestTimingGateIsEnforced:
    def test_unset_is_advisory(self) -> None:
        assert timing_gate_is_enforced() is False

    @pytest.mark.parametrize("value", ["true", "1", "TRUE", "yes"])
    def test_ci_enables_enforcement(self, value: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CI", value)
        assert timing_gate_is_enforced() is True

    @pytest.mark.parametrize("value", ["", "0", "false", "no", "  "])
    def test_falsey_ci_stays_advisory(self, value: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """A runner exporting `CI=false` must not flip the gate on."""
        monkeypatch.setenv("CI", value)
        assert timing_gate_is_enforced() is False

    def test_strict_flag_enables_enforcement_locally(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(STRICT_ENV, "1")
        assert timing_gate_is_enforced() is True


class TestReportTiming:
    def test_within_budget_is_silent(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            _report_timing(within_budget=True, message="unused")

    def test_breach_fails_under_enforcement(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CI", "true")
        # `pytest.fail` raises Failed, which derives from BaseException —
        # a bare `pytest.raises(Exception)` would not catch it.
        with pytest.raises(pytest.fail.Exception, match="180.0ms exceeds"):
            _report_timing(within_budget=False, message="hook_x: 180.0ms exceeds 74.0ms")

    def test_breach_only_warns_locally(self) -> None:
        """The GH-1080 point: a local breach must not turn the suite red."""
        with pytest.warns(UserWarning, match="advisory only"):
            _report_timing(within_budget=False, message="hook_x: 180.0ms exceeds 74.0ms")

    def test_local_warning_names_the_strict_override(self) -> None:
        with pytest.warns(UserWarning, match=STRICT_ENV):
            _report_timing(within_budget=False, message="hook_x: slow")

    def test_local_warning_carries_the_original_message(self) -> None:
        with pytest.warns(UserWarning, match="hook_x: 180.0ms exceeds"):
            _report_timing(within_budget=False, message="hook_x: 180.0ms exceeds 74.0ms")
