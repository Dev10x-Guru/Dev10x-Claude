"""Tests for the accepted-findings catalog and loader (GH-1053)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from dev10x.domain.common.accepted_findings import (
    DEFAULT_ACCEPTED_FINDINGS,
    AcceptedFinding,
    find_acceptance,
)
from dev10x.skills.permission import accepted_findings


@pytest.fixture
def catalog_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "accepted-findings.yaml"
    monkeypatch.setattr(
        "dev10x.skills.permission.accepted_findings.Dev10xConfigDir.accepted_findings_yaml",
        classmethod(lambda cls: path),
    )
    return path


class TestFindAcceptance:
    def test_matches_rule_and_classification(self) -> None:
        entry = AcceptedFinding(
            rule="Bash(git clean -fd:*)",
            rationale="scratch worktrees",
            classifications=frozenset({"REDUNDANT"}),
        )
        found = find_acceptance(
            rule="Bash(git clean -fd:*)",
            classification="REDUNDANT",
            catalog=(entry,),
        )
        assert found is entry

    def test_classification_outside_the_entry_is_not_covered(self) -> None:
        entry = AcceptedFinding(
            rule="Bash(git clean -fd:*)",
            rationale="scratch worktrees",
            classifications=frozenset({"REDUNDANT"}),
        )
        assert (
            find_acceptance(
                rule="Bash(git clean -fd:*)",
                classification="WILDCARD_ESCAPE",
                catalog=(entry,),
            )
            is None
        )

    def test_empty_classifications_cover_every_finding(self) -> None:
        entry = AcceptedFinding(rule="Bash(x:*)", rationale="all of it")
        assert (
            find_acceptance(rule="Bash(x:*)", classification="ANYTHING", catalog=(entry,)) is entry
        )

    def test_unknown_rule_is_not_covered(self) -> None:
        assert find_acceptance(rule="Bash(y:*)", classification="REDUNDANT", catalog=()) is None


class TestShippedDefaults:
    @pytest.mark.parametrize(
        "rule",
        [
            "Bash(git reset --hard:*)",
            "Bash(git push --force:*)",
            "Bash(git push -f:*)",
            "Bash(git branch -D:*)",
            "Bash(git branch -d:*)",
            "Bash(git branch --delete:*)",
        ],
    )
    def test_ruled_family_is_accepted_by_design(self, rule: str) -> None:
        assert (
            find_acceptance(
                rule=rule,
                classification="REDUNDANT",
                catalog=DEFAULT_ACCEPTED_FINDINGS,
            )
            is not None
        )

    def test_every_shipped_entry_cites_the_ruling_that_added_it(self) -> None:
        assert all(re.search(r"GH-\d+", entry.rationale) for entry in DEFAULT_ACCEPTED_FINDINGS), (
            "a shipped acceptance without a ticket reference cannot be re-litigated later"
        )


class TestLoadAcceptedFindings:
    def test_missing_file_yields_the_shipped_defaults(self, catalog_path: Path) -> None:
        assert accepted_findings.load_accepted_findings() == DEFAULT_ACCEPTED_FINDINGS

    def test_user_entry_leads_the_shipped_defaults(self, catalog_path: Path) -> None:
        catalog_path.write_text(
            'accepted:\n  - rule: "Bash(git clean -fd:*)"\n    rationale: "mine"\n',
            encoding="utf-8",
        )
        catalog = accepted_findings.load_accepted_findings()
        assert catalog[0].rule == "Bash(git clean -fd:*)"
        assert catalog[0].source == str(catalog_path)
        assert catalog[1:] == DEFAULT_ACCEPTED_FINDINGS

    def test_classifications_are_normalized_to_upper_case(self, catalog_path: Path) -> None:
        catalog_path.write_text(
            'accepted:\n  - rule: "Bash(x:*)"\n    classifications: [redundant]\n',
            encoding="utf-8",
        )
        assert accepted_findings.load_accepted_findings()[0].classifications == frozenset(
            {"REDUNDANT"}
        )

    def test_rejected_reopens_a_shipped_acceptance(self, catalog_path: Path) -> None:
        catalog_path.write_text(
            'rejected:\n  - "Bash(git push -f:*)"\n',
            encoding="utf-8",
        )
        catalog = accepted_findings.load_accepted_findings()
        assert all(entry.rule != "Bash(git push -f:*)" for entry in catalog)
        assert any(entry.rule == "Bash(git push --force:*)" for entry in catalog)

    def test_malformed_yaml_falls_back_to_the_defaults(self, catalog_path: Path) -> None:
        catalog_path.write_text("accepted: [unclosed\n", encoding="utf-8")
        assert accepted_findings.load_accepted_findings() == DEFAULT_ACCEPTED_FINDINGS

    def test_non_mapping_document_falls_back_to_the_defaults(self, catalog_path: Path) -> None:
        catalog_path.write_text("- just a list\n", encoding="utf-8")
        assert accepted_findings.load_accepted_findings() == DEFAULT_ACCEPTED_FINDINGS

    def test_accepted_must_be_a_list(self, catalog_path: Path) -> None:
        catalog_path.write_text("accepted: nope\n", encoding="utf-8")
        assert accepted_findings.load_accepted_findings() == DEFAULT_ACCEPTED_FINDINGS

    def test_rejected_must_be_a_list(self, catalog_path: Path) -> None:
        catalog_path.write_text("rejected: nope\n", encoding="utf-8")
        assert accepted_findings.load_accepted_findings() == DEFAULT_ACCEPTED_FINDINGS

    def test_entry_without_a_rule_is_skipped(self, catalog_path: Path) -> None:
        catalog_path.write_text(
            'accepted:\n  - rationale: "no rule here"\n  - "not a mapping"\n',
            encoding="utf-8",
        )
        assert accepted_findings.load_accepted_findings() == DEFAULT_ACCEPTED_FINDINGS

    def test_entry_defaults_its_rationale(self, catalog_path: Path) -> None:
        catalog_path.write_text('accepted:\n  - rule: "Bash(x:*)"\n', encoding="utf-8")
        assert accepted_findings.load_accepted_findings()[0].rationale == "accepted by the user"

    def test_string_classification_is_wrapped(self, catalog_path: Path) -> None:
        catalog_path.write_text(
            'accepted:\n  - rule: "Bash(x:*)"\n    classifications: redundant\n',
            encoding="utf-8",
        )
        assert accepted_findings.load_accepted_findings()[0].classifications == frozenset(
            {"REDUNDANT"}
        )

    def test_unusable_classifications_value_covers_every_finding(self, catalog_path: Path) -> None:
        catalog_path.write_text(
            'accepted:\n  - rule: "Bash(x:*)"\n    classifications: 42\n',
            encoding="utf-8",
        )
        assert accepted_findings.load_accepted_findings()[0].classifications == frozenset()
