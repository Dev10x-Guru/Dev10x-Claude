"""Tests for the doctor acceptance catalog and loader (GH-1321)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.domain.common.doctor_acceptance import (
    DEFAULT_ACCEPTED_DOCTOR_FINDINGS,
    AcceptedDoctorFinding,
    find_doctor_acceptance,
)
from dev10x.skills.doctor import acceptance


@pytest.fixture
def catalog_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "doctor-accepted-findings.yaml"
    monkeypatch.setattr(
        "dev10x.skills.doctor.acceptance.Dev10xConfigDir.doctor_accepted_findings_yaml",
        lambda: path,
    )
    return path


def write(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


class TestCovers:
    def test_matches_strategy_and_exact_location(self) -> None:
        entry = AcceptedDoctorFinding(strategy="s", rationale="r", location="/a")

        assert entry.covers(strategy="s", location="/a")

    def test_default_location_covers_every_finding_of_the_strategy(self) -> None:
        entry = AcceptedDoctorFinding(strategy="s", rationale="r")

        assert entry.covers(strategy="s", location="/anywhere")

    def test_another_strategy_is_not_covered(self) -> None:
        entry = AcceptedDoctorFinding(strategy="s", rationale="r")

        assert not entry.covers(strategy="other", location="/a")

    def test_another_location_is_not_covered(self) -> None:
        entry = AcceptedDoctorFinding(strategy="s", rationale="r", location="/a")

        assert not entry.covers(strategy="s", location="/b")


class TestFindAcceptance:
    def test_first_match_wins(self) -> None:
        first = AcceptedDoctorFinding(strategy="s", rationale="user", source="overlay")
        second = AcceptedDoctorFinding(strategy="s", rationale="shipped")

        found = find_doctor_acceptance(strategy="s", location="/a", catalog=(first, second))

        assert found is first

    def test_no_match_is_none(self) -> None:
        assert find_doctor_acceptance(strategy="s", location="/a", catalog=()) is None


class TestShippedDefaults:
    def test_nothing_is_accepted_out_of_the_box(self) -> None:
        # GH-1222's narrowing noise is answered by severity grading, not
        # by a shipped suppression that would also mask a real duplicate.
        assert DEFAULT_ACCEPTED_DOCTOR_FINDINGS == ()


class TestLoader:
    def test_missing_file_yields_the_shipped_defaults(self, catalog_path: Path) -> None:
        assert acceptance.load_doctor_acceptances() == DEFAULT_ACCEPTED_DOCTOR_FINDINGS

    def test_parses_a_complete_entry(self, catalog_path: Path) -> None:
        write(
            catalog_path,
            "accepted:\n"
            "  - strategy: ask-shadows-allow\n"
            '    location: "*/settings.local.json"\n'
            "    rationale: deliberate narrow denies\n",
        )

        [entry] = acceptance.load_doctor_acceptances()

        assert entry.strategy == "ask-shadows-allow"
        assert entry.location == "*/settings.local.json"
        assert entry.rationale == "deliberate narrow denies"
        assert entry.source == str(catalog_path)

    def test_omitted_location_becomes_the_any_glob(self, catalog_path: Path) -> None:
        write(catalog_path, "accepted:\n  - strategy: s\n    rationale: r\n")

        assert acceptance.load_doctor_acceptances()[0].location == "*"

    def test_entry_without_a_rationale_is_rejected(self, catalog_path: Path) -> None:
        # An unexplained suppression cannot be audited six months later.
        write(catalog_path, "accepted:\n  - strategy: s\n")

        assert acceptance.load_doctor_acceptances() == ()

    def test_entry_without_a_strategy_is_rejected(self, catalog_path: Path) -> None:
        write(catalog_path, "accepted:\n  - rationale: r\n")

        assert acceptance.load_doctor_acceptances() == ()

    def test_blank_rationale_is_rejected(self, catalog_path: Path) -> None:
        write(catalog_path, 'accepted:\n  - strategy: s\n    rationale: "   "\n')

        assert acceptance.load_doctor_acceptances() == ()

    def test_non_mapping_entry_is_skipped(self, catalog_path: Path) -> None:
        write(catalog_path, "accepted:\n  - just-a-string\n")

        assert acceptance.load_doctor_acceptances() == ()

    def test_non_list_accepted_is_ignored(self, catalog_path: Path) -> None:
        write(catalog_path, "accepted: nope\n")

        assert acceptance.load_doctor_acceptances() == ()

    def test_absent_accepted_key_is_ignored(self, catalog_path: Path) -> None:
        write(catalog_path, "other: 1\n")

        assert acceptance.load_doctor_acceptances() == ()

    def test_non_mapping_document_is_ignored(self, catalog_path: Path) -> None:
        write(catalog_path, "- a\n- b\n")

        assert acceptance.load_doctor_acceptances() == DEFAULT_ACCEPTED_DOCTOR_FINDINGS

    def test_malformed_yaml_is_ignored(self, catalog_path: Path) -> None:
        write(catalog_path, "accepted: [unclosed\n")

        assert acceptance.load_doctor_acceptances() == DEFAULT_ACCEPTED_DOCTOR_FINDINGS

    def test_unreadable_file_is_ignored(
        self,
        catalog_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        write(catalog_path, "accepted: []\n")
        monkeypatch.setattr(
            Path,
            "read_text",
            lambda self, encoding=None: (_ for _ in ()).throw(OSError("denied")),
        )

        assert acceptance.load_doctor_acceptances() == DEFAULT_ACCEPTED_DOCTOR_FINDINGS

    def test_non_string_location_falls_back_to_the_any_glob(self, catalog_path: Path) -> None:
        write(catalog_path, "accepted:\n  - strategy: s\n    rationale: r\n    location: 7\n")

        assert acceptance.load_doctor_acceptances()[0].location == "*"
