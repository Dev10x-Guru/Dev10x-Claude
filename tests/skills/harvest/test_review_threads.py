"""Tests for dev10x.skills.harvest.review_threads (GH-345)."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import AsyncMock, patch

import pytest

from dev10x.domain.common.result import ErrorResult, SuccessResult
from dev10x.skills.harvest.review_threads import (
    ReviewComment,
    _fetch_pr_review_comments,
    fetch_review_comments,
    fetch_review_comments_multi,
)


def _completed(
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


_COMMENT_FIXTURE: dict = {
    "id": 101,
    "body": "This variable should be named `payment_method`, not `pm`.",
    "path": "src/payments/models.py",
    "line": 42,
    "original_line": 42,
    "commit_id": "abc123def456",
    "created_at": "2026-05-01T10:00:00Z",
    "pull_request_review_id": 999,
    "in_reply_to_id": None,
    "user": {"login": "reviewer1"},
}

_REPLY_FIXTURE: dict = {
    **_COMMENT_FIXTURE,
    "id": 102,
    "body": "Agreed, will fix.",
    "in_reply_to_id": 101,
    "user": {"login": "author1"},
}


class TestReviewCommentFromGhJson:
    def test_parses_full_payload(self):
        comment = ReviewComment.from_gh_json(_COMMENT_FIXTURE, pr_number=42, repo="owner/repo")

        assert comment.comment_id == 101
        assert comment.body == "This variable should be named `payment_method`, not `pm`."
        assert comment.path == "src/payments/models.py"
        assert comment.line == 42
        assert comment.author == "reviewer1"
        assert comment.review_id == 999
        assert comment.in_reply_to_id is None
        assert comment.pr_number == 42
        assert comment.repo == "owner/repo"

    def test_is_reply_false_for_root_comment(self):
        comment = ReviewComment.from_gh_json(_COMMENT_FIXTURE, pr_number=42, repo="owner/repo")
        assert comment.is_reply is False

    def test_is_reply_true_for_reply_comment(self):
        comment = ReviewComment.from_gh_json(_REPLY_FIXTURE, pr_number=42, repo="owner/repo")
        assert comment.is_reply is True

    def test_missing_user_defaults_to_empty_string(self):
        data = {**_COMMENT_FIXTURE, "user": None}
        comment = ReviewComment.from_gh_json(data, pr_number=1, repo="owner/repo")
        assert comment.author == ""

    def test_none_body_normalised_to_empty_string(self):
        data = {**_COMMENT_FIXTURE, "body": None}
        comment = ReviewComment.from_gh_json(data, pr_number=1, repo="owner/repo")
        assert comment.body == ""

    def test_none_path_normalised_to_empty_string(self):
        data = {**_COMMENT_FIXTURE, "path": None}
        comment = ReviewComment.from_gh_json(data, pr_number=1, repo="owner/repo")
        assert comment.path == ""


class TestFetchReviewComments:
    @pytest.mark.asyncio
    @patch("dev10x.skills.harvest.review_threads.async_run", new_callable=AsyncMock)
    async def test_returns_parsed_comments_single_page(self, mock_run: AsyncMock):
        mock_run.side_effect = [
            _completed(stdout=json.dumps([_COMMENT_FIXTURE])),
            _completed(stdout=json.dumps([])),
        ]

        result = await fetch_review_comments(repo="owner/repo", pr_numbers=[42])

        assert isinstance(result, SuccessResult)
        assert len(result.value) == 1
        assert result.value[0].comment_id == 101

    @pytest.mark.asyncio
    @patch("dev10x.skills.harvest.review_threads.async_run", new_callable=AsyncMock)
    async def test_paginates_until_empty_page(self, mock_run: AsyncMock):
        page1 = [_COMMENT_FIXTURE]
        page2 = [{**_COMMENT_FIXTURE, "id": 200}]
        mock_run.side_effect = [
            _completed(stdout=json.dumps(page1)),
            _completed(stdout=json.dumps(page2)),
            _completed(stdout=json.dumps([])),
        ]

        result = await _fetch_pr_review_comments(repo="owner/repo", pr_number=42, page_size=1)

        assert isinstance(result, SuccessResult)
        assert len(result.value) == 2

    @pytest.mark.asyncio
    @patch("dev10x.skills.harvest.review_threads.async_run", new_callable=AsyncMock)
    async def test_empty_pr_numbers_returns_empty_list(self, mock_run: AsyncMock):
        result = await fetch_review_comments(repo="owner/repo", pr_numbers=[])

        assert isinstance(result, SuccessResult)
        assert result.value == []
        mock_run.assert_not_called()

    @pytest.mark.asyncio
    @patch("dev10x.skills.harvest.review_threads.async_run", new_callable=AsyncMock)
    async def test_combines_comments_from_multiple_prs(self, mock_run: AsyncMock):
        comment_pr1 = _COMMENT_FIXTURE
        comment_pr2 = {**_COMMENT_FIXTURE, "id": 201}
        # With the default page_size=100, a single-item page triggers early exit
        # (len(items) < page_size), so each PR needs exactly one fetch call.
        mock_run.side_effect = [
            _completed(stdout=json.dumps([comment_pr1])),
            _completed(stdout=json.dumps([comment_pr2])),
        ]

        result = await fetch_review_comments(repo="owner/repo", pr_numbers=[42, 43])

        assert isinstance(result, SuccessResult)
        assert len(result.value) == 2
        pr_numbers = {c.pr_number for c in result.value}
        assert pr_numbers == {42, 43}

    @pytest.mark.asyncio
    @patch("dev10x.skills.harvest.review_threads.async_run", new_callable=AsyncMock)
    async def test_failed_pr_is_skipped_not_raised(self, mock_run: AsyncMock):
        mock_run.side_effect = [
            _completed(returncode=1, stderr="forbidden"),
        ]

        result = await fetch_review_comments(repo="owner/repo", pr_numbers=[42])

        assert isinstance(result, SuccessResult)
        assert result.value == []

    @pytest.mark.asyncio
    @patch("dev10x.skills.harvest.review_threads.async_run", new_callable=AsyncMock)
    async def test_gh_api_endpoint_includes_repo_and_pr(self, mock_run: AsyncMock):
        mock_run.return_value = _completed(stdout=json.dumps([]))

        await fetch_review_comments(repo="owner/repo", pr_numbers=[99])

        args = mock_run.call_args.kwargs["args"]
        assert "gh" in args
        assert "api" in args
        endpoint = args[-1]
        assert "repos/owner/repo/pulls/99/comments" in endpoint


class TestFetchReviewCommentsMulti:
    @pytest.mark.asyncio
    @patch("dev10x.skills.harvest.review_threads.async_run", new_callable=AsyncMock)
    async def test_returns_mapping_per_repo(self, mock_run: AsyncMock):
        mock_run.side_effect = [
            _completed(stdout=json.dumps([_COMMENT_FIXTURE])),
            _completed(stdout=json.dumps([])),
            _completed(stdout=json.dumps([])),
        ]

        result = await fetch_review_comments_multi(
            repo_prs={"owner/repo-a": [42], "owner/repo-b": []}
        )

        assert isinstance(result, SuccessResult)
        assert set(result.value.keys()) == {"owner/repo-a", "owner/repo-b"}
        assert len(result.value["owner/repo-a"]) == 1
        assert result.value["owner/repo-b"] == []

    @pytest.mark.asyncio
    async def test_empty_repo_prs_returns_error(self):
        result = await fetch_review_comments_multi(repo_prs={})

        assert isinstance(result, ErrorResult)
