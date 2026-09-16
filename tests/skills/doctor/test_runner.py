"""Tests for the non-interactive doctor sweep (GH-1321)."""

from __future__ import annotations

import pytest

from dev10x.domain.common.doctor_acceptance import AcceptedDoctorFinding
from dev10x.domain.common.result import ErrorResult, SuccessResult
from dev10x.skills.doctor.runner import run_doctor
from dev10x.skills.doctor.strategy import Context, Finding, Remediation, Strategy


def finding(*, strategy_id: str = "s1", severity: str = "drift", location: str = "/a") -> Finding:
    return Finding(
        strategy_id=strategy_id,
        severity=severity,  # type: ignore[arg-type]
        location=location,
        evidence="e",
        proposed_fix="f",
    )


def strategy(*, id: str = "s1", findings: list[Finding] | None = None) -> Strategy:
    return Strategy(
        id=id,
        description="d",
        detect=lambda _context: list(findings or []),
        remediate=lambda f: Remediation(kind="edit_settings", target=f.location),
    )


def payload(result: SuccessResult | ErrorResult) -> dict:
    assert isinstance(result, SuccessResult)
    return result.to_dict()


@pytest.fixture
def context() -> Context:
    return Context()


class TestPartitioning:
    def test_an_unaccepted_finding_is_reported(self, context: Context) -> None:
        result = run_doctor(context=context, strategies=[strategy(findings=[finding()])])

        assert len(payload(result)["findings"]) == 1

    def test_an_accepted_finding_is_moved_not_dropped(self, context: Context) -> None:
        # Suppression that hides is how a baseline rots: the finding is
        # still detected, still returned, still counted.
        result = run_doctor(
            context=context,
            strategies=[strategy(findings=[finding()])],
            accepted=(AcceptedDoctorFinding(strategy="s1", rationale="ratified", location="/a"),),
        )

        body = payload(result)
        assert body["findings"] == []
        assert body["accepted"][0]["rationale"] == "ratified"
        assert body["counts"]["accepted"] == 1

    def test_an_accepted_finding_does_not_block(self, context: Context) -> None:
        result = run_doctor(
            context=context,
            strategies=[strategy(findings=[finding(severity="critical")])],
            accepted=(AcceptedDoctorFinding(strategy="s1", rationale="r"),),
        )

        assert payload(result)["blocking"] == 0

    def test_acceptance_is_scoped_to_its_location(self, context: Context) -> None:
        result = run_doctor(
            context=context,
            strategies=[strategy(findings=[finding(location="/b")])],
            accepted=(AcceptedDoctorFinding(strategy="s1", rationale="r", location="/a"),),
        )

        assert len(payload(result)["findings"]) == 1

    def test_acceptance_location_matches_as_a_glob(self, context: Context) -> None:
        result = run_doctor(
            context=context,
            strategies=[strategy(findings=[finding(location="/w/3/.claude/settings.json")])],
            accepted=(
                AcceptedDoctorFinding(strategy="s1", rationale="r", location="*/settings.json"),
            ),
        )

        assert payload(result)["findings"] == []

    def test_acceptance_is_scoped_to_its_strategy(self, context: Context) -> None:
        result = run_doctor(
            context=context,
            strategies=[strategy(findings=[finding(strategy_id="other")])],
            accepted=(AcceptedDoctorFinding(strategy="s1", rationale="r"),),
        )

        assert len(payload(result)["findings"]) == 1


class TestStaleAcceptances:
    def test_an_entry_matching_nothing_is_reported(self, context: Context) -> None:
        result = run_doctor(
            context=context,
            strategies=[strategy(findings=[])],
            accepted=(AcceptedDoctorFinding(strategy="gone", rationale="r", location="/a"),),
        )

        assert payload(result)["stale_acceptances"] == [
            {"strategy": "gone", "location": "/a", "source": "shipped"}
        ]

    def test_a_used_entry_is_not_stale(self, context: Context) -> None:
        result = run_doctor(
            context=context,
            strategies=[strategy(findings=[finding()])],
            accepted=(AcceptedDoctorFinding(strategy="s1", rationale="r", location="/a"),),
        )

        assert payload(result)["stale_acceptances"] == []


class TestThreshold:
    def test_suggestions_do_not_block_by_default(self, context: Context) -> None:
        result = run_doctor(
            context=context,
            strategies=[strategy(findings=[finding(severity="suggestion")])],
        )

        assert payload(result)["blocking"] == 0

    def test_drift_blocks_by_default(self, context: Context) -> None:
        result = run_doctor(context=context, strategies=[strategy(findings=[finding()])])

        assert payload(result)["blocking"] == 1

    def test_a_raised_threshold_spares_drift(self, context: Context) -> None:
        result = run_doctor(
            context=context,
            strategies=[strategy(findings=[finding()])],
            threshold="critical",
        )

        assert payload(result)["blocking"] == 0

    def test_a_lowered_threshold_blocks_on_suggestions(self, context: Context) -> None:
        result = run_doctor(
            context=context,
            strategies=[strategy(findings=[finding(severity="suggestion")])],
            threshold="suggestion",
        )

        assert payload(result)["blocking"] == 1

    def test_an_unknown_severity_ranks_lowest(self, context: Context) -> None:
        # A user strategy inventing a grade must not become the most
        # severe thing in the run by accident.
        result = run_doctor(
            context=context,
            strategies=[strategy(findings=[finding(severity="spicy")])],
        )

        body = payload(result)
        assert body["blocking"] == 0
        assert body["counts"]["spicy"] == 1


class TestFailure:
    def test_a_raising_strategy_fails_the_run_with_attribution(self, context: Context) -> None:
        def boom(_context: Context) -> list[Finding]:
            raise RuntimeError("no settings")

        broken = Strategy(id="broken", description="d", detect=boom, remediate=lambda f: None)  # type: ignore[arg-type,return-value]

        result = run_doctor(context=context, strategies=[broken])

        assert isinstance(result, ErrorResult)
        assert result.to_dict()["strategy_id"] == "broken"


class TestReporting:
    def test_strategies_run_are_named(self, context: Context) -> None:
        result = run_doctor(
            context=context,
            strategies=[strategy(id="a"), strategy(id="b")],
        )

        assert payload(result)["strategies_run"] == ["a", "b"]

    def test_the_shipped_registry_is_the_default(self, context: Context) -> None:
        result = run_doctor(context=context)

        assert "read-deny-phantom" in payload(result)["strategies_run"]
