"""Tests for collect_prs: merged-PR batch fetch/matching (GH-550) and
pure-logic helpers (GH-587 F4a)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from dev10x.skills.release.collect_prs import (
    MERGED_PR_FETCH_LIMIT,
    Commit,
    collect_ticket_groups,
    fetch_merged_prs,
    find_matching_prs,
    find_reverted_shas,
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


def _commit(
    sha: str,
    subject: str,
    is_revert: bool = False,
    ticket_id: str | None = None,
    category: str = "feature",
    gitmoji: str = "✨",
) -> Commit:
    return Commit(
        sha=sha,
        subject=subject,
        gitmoji=gitmoji,
        category=category,
        ticket_id=ticket_id,
        is_revert=is_revert,
    )


class TestFindRevertedShas:
    def test_empty_list_returns_empty_set(self):
        result = find_reverted_shas(commits=[])
        assert result == set()

    def test_no_reverts_returns_empty_set(self):
        commits = [
            _commit(sha="abc12345", subject="✨ GH-1 Add feature"),
            _commit(sha="def67890", subject="🐛 GH-2 Fix bug"),
        ]
        result = find_reverted_shas(commits=commits)
        assert result == set()

    def test_revert_with_full_sha_in_subject_adds_both(self):
        full_sha = "a" * 40
        commits = [
            _commit(
                sha="aaaaaa1a",
                subject=f"Revert 'Fix something' (was {full_sha})",
                is_revert=True,
            ),
        ]
        result = find_reverted_shas(commits=commits)
        # Adds truncated (first 8 chars) of the full SHA found in subject
        assert "aaaaaaaa" in result
        # Also adds the revert commit's own sha
        assert "aaaaaa1a" in result

    def test_revert_without_sha_in_subject_adds_only_revert_sha(self):
        commits = [
            _commit(
                sha="deadbeef",
                subject="Revert 'Some PR title' without a sha",
                is_revert=True,
            ),
        ]
        result = find_reverted_shas(commits=commits)
        assert result == {"deadbeef"}

    def test_non_revert_with_sha_in_subject_is_ignored(self):
        full_sha = "b" * 40
        commits = [
            _commit(
                sha="c0ffee01",
                subject=f"✨ GH-10 References {full_sha} in message",
                is_revert=False,
            ),
        ]
        result = find_reverted_shas(commits=commits)
        assert result == set()

    def test_multiple_reverts(self):
        sha1 = "1" * 40
        sha2 = "2" * 40
        commits = [
            _commit(sha="aabbccdd", subject=f"Revert X ({sha1})", is_revert=True),
            _commit(sha="11223344", subject=f"Revert Y ({sha2})", is_revert=True),
        ]
        result = find_reverted_shas(commits=commits)
        assert "11111111" in result
        assert "22222222" in result
        assert "aabbccdd" in result
        assert "11223344" in result

    def test_revert_sha_truncated_to_8_chars(self):
        full_sha = "fedcba9876543210" + "a" * 24
        commits = [
            _commit(
                sha="00001111",
                subject=f"Revert commit {full_sha}",
                is_revert=True,
            ),
        ]
        result = find_reverted_shas(commits=commits)
        assert "fedcba98" in result

    @pytest.mark.parametrize(
        "subject",
        [
            "revert 'something'",
            "REVERT something",
            "Revert-and-fix nothing",
        ],
    )
    def test_is_revert_flag_checked_not_subject(self, subject: str):
        # The function uses c.is_revert (set by caller), not re-parsing subject.
        # A commit tagged is_revert=False but with "revert" in subject is NOT treated as revert.
        commits = [_commit(sha="cafebabe", subject=subject, is_revert=False)]
        result = find_reverted_shas(commits=commits)
        assert result == set()


class TestCollectTicketGroups:
    def test_empty_commits_returns_empty_dict(self):
        result = collect_ticket_groups(commits=[], skip_shas=set())
        assert result == {}

    def test_commit_with_ticket_id_grouped_by_ticket(self):
        commits = [
            _commit(sha="aaa11111", subject="✨ GH-1 Feature", ticket_id="GH-1"),
        ]
        result = collect_ticket_groups(commits=commits, skip_shas=set())
        assert "GH-1" in result
        assert len(result["GH-1"]) == 1
        assert result["GH-1"][0].sha == "aaa11111"

    def test_multiple_commits_same_ticket_grouped_together(self):
        commits = [
            _commit(sha="aaa11111", subject="✨ GH-5 Feature part 1", ticket_id="GH-5"),
            _commit(sha="bbb22222", subject="✨ GH-5 Feature part 2", ticket_id="GH-5"),
        ]
        result = collect_ticket_groups(commits=commits, skip_shas=set())
        assert "GH-5" in result
        assert len(result["GH-5"]) == 2

    def test_commit_without_ticket_id_keyed_by_sha(self):
        commits = [
            _commit(sha="orphan01", subject="orphan commit", ticket_id=None),
        ]
        result = collect_ticket_groups(commits=commits, skip_shas=set())
        assert "orphan01" in result
        assert "GH-" not in str(list(result.keys()))

    def test_skipped_sha_excluded(self):
        commits = [
            _commit(sha="skip0001", subject="✨ GH-99 Will be skipped", ticket_id="GH-99"),
        ]
        result = collect_ticket_groups(commits=commits, skip_shas={"skip0001"})
        assert result == {}

    def test_skip_category_excluded(self):
        commits = [
            _commit(
                sha="bump0001",
                subject="🔖 Bump version 1.2.3",
                ticket_id=None,
                category="version_bump",
            ),
        ]
        result = collect_ticket_groups(commits=commits, skip_shas=set())
        assert result == {}

    def test_mix_of_skipped_and_normal_commits(self):
        commits = [
            _commit(sha="keep0001", subject="✨ GH-10 Normal", ticket_id="GH-10"),
            _commit(sha="skip0002", subject="🔖 Bump", category="version_bump"),
            _commit(sha="skip0003", subject="Revert X", ticket_id="GH-11", is_revert=True),
        ]
        result = collect_ticket_groups(commits=commits, skip_shas={"skip0003"})
        assert "GH-10" in result
        # skip0003 is in skip_shas
        assert "GH-11" not in result
        # version_bump category skipped
        assert "skip0002" not in result
        assert len(result) == 1

    def test_distinct_tickets_separate_groups(self):
        commits = [
            _commit(sha="aaa11111", subject="✨ GH-1 Feature A", ticket_id="GH-1"),
            _commit(sha="bbb22222", subject="🐛 GH-2 Fix B", ticket_id="GH-2"),
        ]
        result = collect_ticket_groups(commits=commits, skip_shas=set())
        assert "GH-1" in result
        assert "GH-2" in result
        assert len(result) == 2

    def test_commit_category_not_in_skip_categories_included(self):
        commits = [
            _commit(
                sha="feat0001", subject="✨ GH-3 feature", ticket_id="GH-3", category="feature"
            ),
            _commit(sha="test0001", subject="✅ GH-4 tests", ticket_id="GH-4", category="test"),
        ]
        # "test" is in MAINTENANCE_CATEGORIES but NOT in SKIP_CATEGORIES
        result = collect_ticket_groups(commits=commits, skip_shas=set())
        assert "GH-3" in result
        assert "GH-4" in result

    def test_no_none_ticket_collision(self):
        # Two commits without ticket IDs should each be keyed by their own sha
        commits = [
            _commit(sha="orphan01", subject="orphan 1", ticket_id=None),
            _commit(sha="orphan02", subject="orphan 2", ticket_id=None),
        ]
        result = collect_ticket_groups(commits=commits, skip_shas=set())
        assert "orphan01" in result
        assert "orphan02" in result
        assert len(result) == 2
