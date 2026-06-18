"""Tests for the shared doctor strategy types (GH-518)."""

from __future__ import annotations

import pytest

pytest.importorskip("dev10x.skills.doctor.strategy", reason="dev10x not installed")

from dev10x.skills.doctor.strategy import (  # noqa: E402
    Finding,
    Remediation,
    RemediationData,
)


class _StubData:
    def to_remediation(self, *, finding: Finding) -> Remediation:
        return Remediation(kind="file_issue", target=finding.location)


class TestFindingToRemediation:
    def test_delegates_to_attached_data(self) -> None:
        finding = Finding(
            strategy_id="stub",
            severity="drift",
            location="/tmp/x",
            evidence="e",
            proposed_fix="f",
            data=_StubData(),
        )

        remediation = finding.to_remediation()

        assert remediation.kind == "file_issue"
        assert remediation.target == "/tmp/x"

    def test_raises_when_no_data_attached(self) -> None:
        finding = Finding(
            strategy_id="stub",
            severity="drift",
            location="/tmp/x",
            evidence="e",
            proposed_fix="f",
        )

        with pytest.raises(ValueError, match="no remediation data"):
            finding.to_remediation()

    def test_stub_data_satisfies_protocol(self) -> None:
        assert isinstance(_StubData(), RemediationData)
