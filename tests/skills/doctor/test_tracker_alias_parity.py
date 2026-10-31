"""GH-1668: the doctor reports tracker rules that disagree across MCP server names."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from dev10x.skills.doctor.registry import load_strategies
from dev10x.skills.doctor.strategies.tracker_alias_parity import STRATEGY, detect
from dev10x.skills.doctor.strategy import Context

CLAUDE_AI = "mcp__claude_ai_Linear__"
SERVER = "mcp__linear-server__"
BARE = "mcp__linear__"


def _context(tmp_path: Path, *, allow: list[str], deny: list[str] | None = None) -> Context:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"permissions": {"allow": allow, "deny": deny or []}}))
    return Context(settings_paths=(path,))


def _full(tool: str) -> list[str]:
    return [f"{prefix}{tool}" for prefix in (CLAUDE_AI, SERVER, BARE)]


class TestDetection:
    def test_full_parity_is_clean(self, tmp_path: Path) -> None:
        context = _context(tmp_path, allow=_full("get_issue") + _full("save_issue"))

        assert detect(context) == []

    def test_no_tracker_rules_is_clean(self, tmp_path: Path) -> None:
        assert detect(_context(tmp_path, allow=["Bash(git log:*)"])) == []

    def test_parity_gap_names_the_missing_aliases(self, tmp_path: Path) -> None:
        context = _context(tmp_path, allow=[f"{CLAUDE_AI}list_release_pipelines"])

        [finding] = detect(context)

        assert finding.severity == "drift"
        assert finding.data.rules == (
            f"{SERVER}list_release_pipelines",
            f"{BARE}list_release_pipelines",
        )
        assert finding.data.to_remediation(finding=finding).target == "permissions.allow"

    @pytest.mark.parametrize("prefix", [CLAUDE_AI, SERVER, BARE])
    def test_delete_allowed_under_any_alias_is_critical(self, tmp_path: Path, prefix: str) -> None:
        context = _context(tmp_path, allow=[f"{prefix}delete_comment"])

        [finding] = detect(context)

        assert finding.severity == "critical"
        assert finding.data.rules == (f"{prefix}delete_comment",)
        assert finding.data.to_remediation(finding=finding).target == "permissions.deny"

    def test_denied_delete_is_not_reported(self, tmp_path: Path) -> None:
        context = _context(
            tmp_path,
            allow=[f"{SERVER}delete_comment"],
            deny=[f"{SERVER}delete_comment"],
        )

        assert detect(context) == []

    @pytest.mark.parametrize("pattern", ["delete_*", "delete_comment*", "*", "delete_com*nt"])
    def test_delete_covered_by_a_deny_glob_is_not_reported(
        self, tmp_path: Path, pattern: str
    ) -> None:
        context = _context(
            tmp_path,
            allow=[f"{SERVER}delete_comment"],
            deny=[f"{SERVER}{pattern}"],
        )

        assert detect(context) == []

    def test_deny_glob_under_another_alias_does_not_cover(self, tmp_path: Path) -> None:
        context = _context(
            tmp_path,
            allow=[f"{SERVER}delete_comment"],
            deny=[f"{CLAUDE_AI}delete_*"],
        )

        [finding] = detect(context)

        assert finding.data.rules == (f"{SERVER}delete_comment",)

    def test_non_matching_deny_glob_still_reports(self, tmp_path: Path) -> None:
        context = _context(
            tmp_path,
            allow=[f"{SERVER}delete_comment"],
            deny=[f"{SERVER}remove_*"],
        )

        assert len(detect(context)) == 1

    def test_wildcard_allow_is_not_parity_noise(self, tmp_path: Path) -> None:
        assert detect(_context(tmp_path, allow=[f"{SERVER}*"])) == []

    def test_dead_bash_wrapper_is_reported(self, tmp_path: Path) -> None:
        context = _context(tmp_path, allow=["Bash(mcp__linear-server__get_issue *)"])

        [finding] = detect(context)

        assert finding.severity == "critical"
        assert "mcp__linear-server__get_issue" in finding.proposed_fix

    def test_jira_aliases_are_checked_too(self, tmp_path: Path) -> None:
        context = _context(tmp_path, allow=["mcp__claude_ai_Atlassian_Rovo__getJiraIssue"])

        [finding] = detect(context)

        assert finding.data.rules == (
            "mcp__claude_ai_Atlassian__getJiraIssue",
            "mcp__atlassian__getJiraIssue",
        )

    def test_missing_file_is_skipped(self, tmp_path: Path) -> None:
        assert detect(Context(settings_paths=(tmp_path / "absent.json",))) == []

    @pytest.mark.parametrize(
        "body", ["{not json", "[1]", '{"permissions": 3}', '{"permissions": {}}']
    )
    def test_unreadable_files_are_skipped(self, tmp_path: Path, body: str) -> None:
        path = tmp_path / "settings.json"
        path.write_text(body)

        assert detect(Context(settings_paths=(path,))) == []


def test_remediate_delegates_to_the_finding(tmp_path: Path) -> None:
    [finding] = detect(_context(tmp_path, allow=[f"{SERVER}delete_comment"]))

    assert STRATEGY.remediate(finding).target == "permissions.deny"


def test_strategy_is_registered() -> None:
    assert STRATEGY.id in {strategy.id for strategy in load_strategies()}
