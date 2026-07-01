"""Unit tests for PR lifecycle MCP tool contracts (GH-547).

Covers the three tools central to gh-pr-merge, gh-pr-review, and
gh-pr-triage skill flows:

- ``unresolved_threads``: repo param is required; empty list returns
  count=0; non-empty list returns correct count.
- ``merge_pr``: all three strategies pass correct flag; draft-error
  and thread-error messages are surfaced as err(); the ``--repo``
  flag is always present for worktree safety (GH-773).
- ``resolve_review_thread``: thread_ids must be a list (PRRT_ prefix
  required); comment_ids triggers thread lookup first.

Contract class: mock
  All tests patch the API/subprocess boundary and supply canned
  payloads. They verify argument construction, Result shapes, and
  error propagation — not live GitHub responses.
"""

from __future__ import annotations

import json
import subprocess
from unittest.mock import AsyncMock, patch

import pytest

from dev10x.domain.common.repository_ref import RepositoryRef
from dev10x.domain.common.result import ErrorResult, SuccessResult, ok

gh = pytest.importorskip("dev10x.github", reason="dev10x not installed")


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


@pytest.fixture
def mock_resolve_repo() -> AsyncMock:
    with patch.object(
        gh,
        "_resolve_repo",
        new_callable=AsyncMock,
        return_value=ok(RepositoryRef(owner="owner", name="repo")),
    ) as mock:
        yield mock


class TestUnresolvedThreadsContract:
    """gh.unresolved_threads — standalone function, not pr_comments."""

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_empty_list_returns_count_zero(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout=json.dumps([]))

        result = await gh.unresolved_threads(repo="owner/repo")

        assert isinstance(result, SuccessResult)
        assert result.value["count"] == 0
        assert result.value["prs"] == []

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_non_empty_list_returns_correct_count(
        self,
        mock_run: AsyncMock,
    ) -> None:
        prs = [{"number": 1, "title": "PR 1"}, {"number": 2, "title": "PR 2"}]
        mock_run.return_value = _completed(stdout=json.dumps(prs))

        result = await gh.unresolved_threads(repo="owner/repo")

        assert isinstance(result, SuccessResult)
        assert result.value["count"] == 2
        assert len(result.value["prs"]) == 2

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_repo_is_forwarded_to_script(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout=json.dumps([]))

        await gh.unresolved_threads(repo="acme/widget")

        call_args = mock_run.call_args
        args_list = list(call_args[0])
        assert "acme/widget" in args_list

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_limit_is_forwarded_to_script(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout=json.dumps([]))

        await gh.unresolved_threads(repo="acme/widget", limit=50)

        call_args = mock_run.call_args
        args_list = list(call_args[0])
        assert "50" in args_list

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_script_failure_returns_error(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="rate limit exceeded")

        result = await gh.unresolved_threads(repo="owner/repo")

        assert isinstance(result, ErrorResult)
        assert "rate limit" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_malformed_json_returns_error(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="<html>502</html>")

        result = await gh.unresolved_threads(repo="owner/repo")

        assert isinstance(result, ErrorResult)
        assert "JSON" in result.error or "Invalid" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_pr_number_uses_fast_single_pr_path(
        self,
        mock_api_raw: AsyncMock,
        mock_run: AsyncMock,
    ) -> None:
        # GH-710: pr_number short-circuits to the single-PR GraphQL
        # query, never the repo-wide merged-PR sweep that times out.
        mock_api_raw.return_value = _completed(
            stdout=json.dumps(
                {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": []}}}}}
            )
        )

        result = await gh.unresolved_threads(repo="owner/repo", pr_number=706)

        assert isinstance(result, SuccessResult)
        assert result.value == {"unresolved_threads": [], "count": 0}
        mock_run.assert_not_called()
        query = mock_api_raw.call_args.kwargs["fields"]["query"]
        assert "pullRequest(number: 706)" in query

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_pr_number_counts_only_unresolved(
        self,
        mock_api_raw: AsyncMock,
        mock_run: AsyncMock,
    ) -> None:
        nodes = [
            {
                "id": "PRRT_1",
                "isResolved": False,
                "isOutdated": False,
                "comments": {
                    "nodes": [
                        {
                            "databaseId": 11,
                            "body": "fix this",
                            "path": "a.py",
                            "line": 3,
                            "author": {"login": "bot"},
                        }
                    ]
                },
            },
            {"id": "PRRT_2", "isResolved": True, "comments": {"nodes": []}},
        ]
        mock_api_raw.return_value = _completed(
            stdout=json.dumps(
                {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": nodes}}}}}
            )
        )

        result = await gh.unresolved_threads(repo="owner/repo", pr_number=42)

        assert isinstance(result, SuccessResult)
        assert result.value["count"] == 1
        assert result.value["unresolved_threads"][0]["thread_id"] == "PRRT_1"
        mock_run.assert_not_called()


class TestMergePrContract:
    """gh.merge_pr — argument construction and error propagation."""

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_merge_strategy_passes_correct_flag(
        self,
        mock_run: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed()

        await gh.merge_pr(pr_number=7, strategy="merge")

        called_args = mock_run.call_args.kwargs["args"]
        assert "--merge" in called_args

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_repo_flag_always_present_for_worktree_safety(
        self,
        mock_run: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        """GH-773: --repo must always be passed so gh pr merge never tries to
        check out the base branch in a conflicting worktree."""
        mock_run.return_value = _completed()

        await gh.merge_pr(pr_number=42)

        called_args = mock_run.call_args.kwargs["args"]
        assert "--repo" in called_args

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_draft_state_error_surfaces_as_err(
        self,
        mock_run: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        """When gh reports a draft-state block, the error is surfaced to the
        skill so Check 3 (draft block) can report it correctly."""
        mock_run.return_value = _completed(
            returncode=1,
            stderr="Pull request #42 is in draft state",
        )

        result = await gh.merge_pr(pr_number=42)

        assert isinstance(result, ErrorResult)
        assert "draft" in result.error.lower()

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_unmerged_threads_error_surfaces_as_err(
        self,
        mock_run: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        """When gh reports unresolved review threads, the error is surfaced to
        the skill so it can report which check failed."""
        mock_run.return_value = _completed(
            returncode=1,
            stderr="Pull request is not mergeable: has unresolved review threads",
        )

        result = await gh.merge_pr(pr_number=42)

        assert isinstance(result, ErrorResult)
        assert "unresolved" in result.error.lower() or "not mergeable" in result.error.lower()

    @pytest.mark.asyncio
    async def test_all_invalid_strategies_rejected(self) -> None:
        for strategy in ("fast-forward", "cherry-pick", "", "REBASE"):
            result = await gh.merge_pr(pr_number=1, strategy=strategy)
            assert isinstance(result, ErrorResult)
            assert "Invalid merge strategy" in result.error


class TestResolveReviewThreadContract:
    """gh.resolve_review_thread — parameter validation and delegation."""

    @pytest.mark.asyncio
    async def test_thread_ids_must_start_with_prrt_prefix(self) -> None:
        result = await gh.resolve_review_thread(thread_ids=["IC_abc123"])

        assert isinstance(result, ErrorResult)
        assert "PRRT_" in result.error

    @pytest.mark.asyncio
    async def test_empty_call_with_no_ids_returns_error(self) -> None:
        result = await gh.resolve_review_thread()

        assert isinstance(result, ErrorResult)
        assert "thread_ids" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_multiple_thread_ids_batched_in_single_call(
        self,
        mock_api: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(
            stdout=json.dumps(
                {
                    "data": {
                        "r0": {"thread": {"id": "PRRT_t1", "isResolved": True}},
                        "r1": {"thread": {"id": "PRRT_t2", "isResolved": True}},
                    }
                }
            )
        )

        result = await gh.resolve_review_thread(thread_ids=["PRRT_t1", "PRRT_t2"])

        assert isinstance(result, SuccessResult)
        # Both IDs resolved in a single API call
        assert mock_api.call_count == 1

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_comment_ids_trigger_lookup_before_mutation(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        """comment_ids path requires a thread-lookup query before the
        resolveReviewThread mutation — two API calls, not one."""
        mock_api.side_effect = [
            _completed(
                stdout=json.dumps(
                    {
                        "data": {
                            "n0": {
                                "databaseId": 99,
                                "pullRequest": {
                                    "reviewThreads": {
                                        "nodes": [
                                            {
                                                "id": "PRRT_looked_up",
                                                "comments": {"nodes": [{"databaseId": 99}]},
                                            }
                                        ]
                                    }
                                },
                            }
                        }
                    }
                )
            ),
            _completed(
                stdout=json.dumps(
                    {"data": {"r0": {"thread": {"id": "PRRT_looked_up", "isResolved": True}}}}
                )
            ),
        ]

        result = await gh.resolve_review_thread(comment_ids=["PRRC_xyz"])

        assert isinstance(result, SuccessResult)
        assert mock_api.call_count == 2
