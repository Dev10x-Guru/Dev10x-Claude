"""Tests for the read-deny-phantom strategy (GH-1321)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.skills.doctor.registry import DEFAULT_STRATEGY_MODULES
from dev10x.skills.doctor.strategies.read_deny_phantom import STRATEGY, detect
from dev10x.skills.doctor.strategy import Context


def settings(tmp_path: Path, *, deny: object, name: str = "settings.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps({"permissions": {"deny": deny}}), encoding="utf-8")
    return path


@pytest.fixture
def absolute_denies(tmp_path: Path) -> Path:
    return settings(tmp_path, deny=["Read(/etc/shadow)", "Read(~/.ssh/**)", "Bash(sudo:*)"])


class TestDetect:
    def test_reports_one_finding_per_settings_file(self, absolute_denies: Path) -> None:
        findings = detect(Context(settings_paths=(absolute_denies,)))

        assert len(findings) == 1

    def test_names_every_absolute_read_deny(self, absolute_denies: Path) -> None:
        [finding] = detect(Context(settings_paths=(absolute_denies,)))

        assert "Read(/etc/shadow)" in finding.evidence
        assert "Read(~/.ssh/**)" in finding.evidence

    def test_ignores_non_read_denies(self, absolute_denies: Path) -> None:
        [finding] = detect(Context(settings_paths=(absolute_denies,)))

        assert "Bash(sudo:*)" not in finding.evidence

    def test_never_blocks_a_ci_run(self, absolute_denies: Path) -> None:
        # Advisory by construction: the deny is correct, only the search
        # tool should change. A `suggestion` is below the runner's
        # default threshold.
        [finding] = detect(Context(settings_paths=(absolute_denies,)))

        assert finding.severity == "suggestion"

    def test_proposes_grep_rather_than_removing_the_deny(self, absolute_denies: Path) -> None:
        [finding] = detect(Context(settings_paths=(absolute_denies,)))

        assert "Grep" in finding.proposed_fix
        assert "Leave the denies alone" in finding.proposed_fix

    @pytest.mark.parametrize(
        "pattern",
        ["$HOME/.aws/**", "${HOME}/.netrc"],
    )
    def test_home_variable_spellings_are_absolute(self, tmp_path: Path, pattern: str) -> None:
        path = settings(tmp_path, deny=[f"Read({pattern})"])

        assert detect(Context(settings_paths=(path,))) != []

    def test_relative_deny_is_silent(self, tmp_path: Path) -> None:
        # Not re-rooted, because it was never rooted anywhere else.
        path = settings(tmp_path, deny=["Read(./secrets/**)", "Read(src/**)"])

        assert detect(Context(settings_paths=(path,))) == []

    def test_missing_file_is_silent(self, tmp_path: Path) -> None:
        assert detect(Context(settings_paths=(tmp_path / "absent.json",))) == []

    def test_malformed_json_is_silent(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        path.write_text("{not json", encoding="utf-8")

        assert detect(Context(settings_paths=(path,))) == []

    def test_non_mapping_permissions_is_silent(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"permissions": "nope"}), encoding="utf-8")

        assert detect(Context(settings_paths=(path,))) == []

    def test_non_list_deny_is_silent(self, tmp_path: Path) -> None:
        assert detect(Context(settings_paths=(settings(tmp_path, deny="nope"),))) == []

    def test_non_string_deny_entry_is_skipped(self, tmp_path: Path) -> None:
        assert detect(Context(settings_paths=(settings(tmp_path, deny=[{"a": 1}]),))) == []


class TestRemediation:
    def test_carries_the_deny_rules_and_the_grep_steer(self, absolute_denies: Path) -> None:
        [finding] = detect(Context(settings_paths=(absolute_denies,)))

        remediation = STRATEGY.remediate(finding)

        assert remediation.action["deny_rules"] == ["Read(/etc/shadow)", "Read(~/.ssh/**)"]
        assert "Grep" in remediation.action["reason"]

    def test_target_is_the_search_habit_not_the_settings_file(
        self,
        absolute_denies: Path,
    ) -> None:
        [finding] = detect(Context(settings_paths=(absolute_denies,)))

        assert STRATEGY.remediate(finding).target == "recursive-read-search"


class TestRegistration:
    def test_strategy_ships_by_default(self) -> None:
        assert "dev10x.skills.doctor.strategies.read_deny_phantom" in DEFAULT_STRATEGY_MODULES

    def test_strategy_id_matches_findings(self, absolute_denies: Path) -> None:
        [finding] = detect(Context(settings_paths=(absolute_denies,)))

        assert finding.strategy_id == STRATEGY.id == "read-deny-phantom"
