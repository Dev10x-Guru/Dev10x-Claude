"""Tests for dev10x.skills.harvest.closed_prs (GH-345)."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import AsyncMock, patch

import pytest

from dev10x.domain.common.result import ErrorResult, SuccessResult
from dev10x.skills.harvest.closed_prs import (
    DEFAULT_LIMIT,
    ClosedPR,
    fetch_closed_prs,
    fetch_closed_prs_multi,
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


_PR_FIXTURE: dict = {
    "number": 42,
    "title": "Enable review harvesting",
    "body": (
        "**When** a dev **wants to** analyse review patterns "
        "**so** they **can** improve code quality."
    ),
    "mergedAt": "2026-05-01T12:00:00Z",
    "closedAt": "2026-05-01T12:00:00Z",
    "state": "MERGED",
    "labels": [{"name": "enhancement"}],
    "author": {"login": "wooyek"},
    "baseRefName": "develop",
}


class TestClosedPRFromGhJson:
    def test_parses_full_payload(self):
        pr = ClosedPR.from_gh_json(_PR_FIXTURE)

        assert pr.number == 42
        assert pr.title == "Enable review harvesting"
        assert pr.state == "MERGED"
        assert pr.merged_at == "2026-05-01T12:00:00Z"
        assert pr.base_ref == "develop"
        assert pr.author == "wooyek"
        assert pr.labels == ["enhancement"]

    def test_missing_author_defaults_to_empty_string(self):
        data = {**_PR_FIXTURE, "author": None}
        pr = ClosedPR.from_gh_json(data)
        assert pr.author == ""

    def test_missing_labels_defaults_to_empty_list(self):
        data = {**_PR_FIXTURE, "labels": []}
        pr = ClosedPR.from_gh_json(data)
        assert pr.labels == []

    def test_plain_string_label_is_preserved(self):
        data = {**_PR_FIXTURE, "labels": ["plain-string"]}
        pr = ClosedPR.from_gh_json(data)
        assert pr.labels == ["plain-string"]

    def test_none_body_normalised_to_empty_string(self):
        data = {**_PR_FIXTURE, "body": None}
        pr = ClosedPR.from_gh_json(data)
        assert pr.body == ""


class TestFetchClosedPRs:
    @pytest.mark.asyncio
    @patch("dev10x.skills.harvest.closed_prs.async_run", new_callable=AsyncMock)
    async def test_returns_parsed_prs_on_success(self, mock_run: AsyncMock):
        mock_run.return_value = _completed(stdout=json.dumps([_PR_FIXTURE]))

        result = await fetch_closed_prs(repo="owner/repo")

        assert isinstance(result, SuccessResult)
        assert len(result.value) == 1
        assert result.value[0].number == 42

    @pytest.mark.asyncio
    @patch("dev10x.skills.harvest.closed_prs.async_run", new_callable=AsyncMock)
    async def test_passes_correct_gh_args(self, mock_run: AsyncMock):
        mock_run.return_value = _completed(stdout=json.dumps([_PR_FIXTURE]))

        await fetch_closed_prs(repo="owner/repo", limit=50, state="closed")

        args = mock_run.call_args.kwargs["args"]
        assert "gh" in args
        assert "pr" in args
        assert "list" in args
        assert "--repo" in args
        assert "owner/repo" in args
        assert "--state" in args
        assert "closed" in args
        assert "--limit" in args
        assert "50" in args

    @pytest.mark.asyncio
    @patch("dev10x.skills.harvest.closed_prs.async_run", new_callable=AsyncMock)
    async def test_returns_empty_list_on_empty_output(self, mock_run: AsyncMock):
        mock_run.return_value = _completed(stdout="")

        result = await fetch_closed_prs(repo="owner/repo")

        assert isinstance(result, SuccessResult)
        assert result.value == []

    @pytest.mark.asyncio
    @patch("dev10x.skills.harvest.closed_prs.async_run", new_callable=AsyncMock)
    async def test_returns_error_on_nonzero_exit(self, mock_run: AsyncMock):
        mock_run.return_value = _completed(returncode=1, stderr="gh: error: bad credentials")

        result = await fetch_closed_prs(repo="owner/repo")

        assert isinstance(result, ErrorResult)
        assert "bad credentials" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.skills.harvest.closed_prs.async_run", new_callable=AsyncMock)
    async def test_returns_error_on_invalid_json(self, mock_run: AsyncMock):
        mock_run.return_value = _completed(stdout="not-json{}")

        result = await fetch_closed_prs(repo="owner/repo")

        assert isinstance(result, ErrorResult)
        assert "parse" in result.error.lower()

    @pytest.mark.asyncio
    @patch("dev10x.skills.harvest.closed_prs.async_run", new_callable=AsyncMock)
    async def test_default_state_is_merged(self, mock_run: AsyncMock):
        mock_run.return_value = _completed(stdout=json.dumps([]))

        await fetch_closed_prs(repo="owner/repo")

        args = mock_run.call_args.kwargs["args"]
        state_idx = args.index("--state")
        assert args[state_idx + 1] == "merged"

    @pytest.mark.asyncio
    @patch("dev10x.skills.harvest.closed_prs.async_run", new_callable=AsyncMock)
    async def test_default_limit_is_applied(self, mock_run: AsyncMock):
        mock_run.return_value = _completed(stdout=json.dumps([]))

        await fetch_closed_prs(repo="owner/repo")

        args = mock_run.call_args.kwargs["args"]
        limit_idx = args.index("--limit")
        assert args[limit_idx + 1] == str(DEFAULT_LIMIT)


class TestFetchClosedPRsMulti:
    @pytest.mark.asyncio
    @patch("dev10x.skills.harvest.closed_prs.async_run", new_callable=AsyncMock)
    async def test_returns_mapping_per_repo(self, mock_run: AsyncMock):
        mock_run.return_value = _completed(stdout=json.dumps([_PR_FIXTURE]))

        result = await fetch_closed_prs_multi(repos=["owner/repo-a", "owner/repo-b"])

        assert isinstance(result, SuccessResult)
        assert set(result.value.keys()) == {"owner/repo-a", "owner/repo-b"}
        assert len(result.value["owner/repo-a"]) == 1

    @pytest.mark.asyncio
    @patch("dev10x.skills.harvest.closed_prs.async_run", new_callable=AsyncMock)
    async def test_failed_repo_maps_to_empty_list(self, mock_run: AsyncMock):
        mock_run.return_value = _completed(returncode=1, stderr="not found")

        result = await fetch_closed_prs_multi(repos=["owner/missing"])

        assert isinstance(result, SuccessResult)
        assert result.value["owner/missing"] == []

    @pytest.mark.asyncio
    async def test_empty_repos_returns_error(self):
        result = await fetch_closed_prs_multi(repos=[])

        assert isinstance(result, ErrorResult)
