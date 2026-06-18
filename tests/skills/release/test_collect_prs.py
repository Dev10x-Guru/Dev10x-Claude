"""Tests for collect_prs merged-PR batch fetch + matching (GH-550)."""

from __future__ import annotations

import json
from unittest.mock import patch

from dev10x.skills.release.collect_prs import (
    MERGED_PR_FETCH_LIMIT,
    fetch_merged_prs,
    find_matching_prs,
)

_RUN = "dev10x.skills.release.collect_prs.run"


class TestFetchMergedPrs:
    def test_single_batch_call_without_search(self) -> None:
        prs = [{"number": 1, "title": "GH-1 x", "body": ""}]
        with patch(_RUN, return_value=json.dumps(prs)) as mock_run:
            result = fetch_merged_prs(repo_path="/repo")
        assert result == prs
        cmd = mock_run.call_args.args[0]
        assert cmd[:3] == ["gh", "pr", "list"]
        assert "--state" in cmd
        assert "merged" in cmd
        assert "--limit" in cmd
        assert str(MERGED_PR_FETCH_LIMIT) in cmd
        # GH-550: no per-ticket --search; one batch call instead.
        assert "--search" not in cmd

    def test_custom_limit_is_passed(self) -> None:
        with patch(_RUN, return_value="[]") as mock_run:
            fetch_merged_prs(repo_path="/repo", limit=42)
        assert "42" in mock_run.call_args.args[0]

    def test_empty_output_returns_empty(self) -> None:
        with patch(_RUN, return_value=""):
            assert fetch_merged_prs(repo_path="/repo") == []

    def test_invalid_json_returns_empty(self) -> None:
        with patch(_RUN, return_value="not json"):
            assert fetch_merged_prs(repo_path="/repo") == []


class TestFindMatchingPrs:
    _PRS = [
        {"number": 1, "title": "✨ GH-1 Add feature", "body": "Fixes: GH-1"},
        {"number": 2, "title": "🐛 Fix bug", "body": "Closes GH-2 and GH-1"},
        {"number": 3, "title": "Unrelated", "body": "no ticket"},
    ]

    def test_matches_ticket_in_title_or_body(self) -> None:
        result = find_matching_prs(ticket_id="GH-1", merged_prs=self._PRS)
        assert {pr["number"] for pr in result} == {1, 2}

    def test_matches_ticket_in_body_only(self) -> None:
        result = find_matching_prs(ticket_id="GH-2", merged_prs=self._PRS)
        assert [pr["number"] for pr in result] == [2]

    def test_no_match_returns_empty(self) -> None:
        assert find_matching_prs(ticket_id="GH-99", merged_prs=self._PRS) == []

    def test_does_not_substring_match_longer_ticket(self) -> None:
        # GH-55 must not match a PR that only references GH-550 (word boundary).
        prs = [{"number": 9, "title": "Fix", "body": "Fixes: GH-550"}]
        assert find_matching_prs(ticket_id="GH-55", merged_prs=prs) == []

    def test_handles_missing_title_and_body(self) -> None:
        assert find_matching_prs(ticket_id="GH-1", merged_prs=[{"number": 5}]) == []

    def test_empty_pr_list(self) -> None:
        assert find_matching_prs(ticket_id="GH-1", merged_prs=[]) == []
