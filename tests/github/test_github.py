from __future__ import annotations

import json
import subprocess
from unittest.mock import AsyncMock, patch

import pytest

from dev10x.domain.repository_ref import RepositoryRef
from dev10x.domain.result import ErrorResult, SuccessResult, ok

gh = pytest.importorskip("dev10x.github", reason="dev10x not installed")


@pytest.fixture
def mock_resolve_repo():
    with patch.object(
        gh,
        "_resolve_repo",
        new_callable=AsyncMock,
        return_value=ok(RepositoryRef(owner="owner", name="repo")),
    ) as mock:
        yield mock


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


class TestPrCommentsResolveSingle:
    @pytest.fixture
    def query_response(self) -> str:
        return json.dumps({"data": {"n0": {"pullRequestReviewThread": {"id": "PRRT_thread123"}}}})

    @pytest.fixture
    def mutation_response(self) -> str:
        return json.dumps(
            {"data": {"r0": {"thread": {"id": "PRRT_thread123", "isResolved": True}}}}
        )

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_resolves_single_comment(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
        query_response: str,
        mutation_response: str,
    ) -> None:
        mock_api.side_effect = [
            _completed(stdout=query_response),
            _completed(stdout=mutation_response),
        ]

        result = await gh.pr_comments(
            action="resolve",
            comment_id="PRRC_comment123",
        )

        assert result.value["data"]["r0"]["thread"]["isResolved"] is True
        assert mock_api.call_count == 2

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_converts_int_comment_id_to_string(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
        query_response: str,
        mutation_response: str,
    ) -> None:
        mock_api.side_effect = [
            _completed(stdout=query_response),
            _completed(stdout=mutation_response),
        ]

        await gh.pr_comments(action="resolve", comment_id=12345)

        query_call = mock_api.call_args_list[0]
        query_str = query_call.kwargs["fields"]["query"]
        assert '"12345"' in query_str

    @pytest.mark.asyncio
    async def test_returns_error_when_no_comment_id(
        self,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        result = await gh.pr_comments(action="resolve")

        assert isinstance(result, ErrorResult)
        assert "comment_id or comment_ids required" in result.error


class TestPrCommentsResolveBatch:
    @pytest.fixture
    def comment_ids(self) -> list[str]:
        return ["PRRC_aaa", "PRRC_bbb", "PRRC_ccc"]

    @pytest.fixture
    def batch_query_response(self) -> str:
        return json.dumps(
            {
                "data": {
                    "n0": {"pullRequestReviewThread": {"id": "PRRT_t1"}},
                    "n1": {"pullRequestReviewThread": {"id": "PRRT_t2"}},
                    "n2": {"pullRequestReviewThread": {"id": "PRRT_t3"}},
                }
            }
        )

    @pytest.fixture
    def batch_mutation_response(self) -> str:
        return json.dumps(
            {
                "data": {
                    "r0": {"thread": {"id": "PRRT_t1", "isResolved": True}},
                    "r1": {"thread": {"id": "PRRT_t2", "isResolved": True}},
                    "r2": {"thread": {"id": "PRRT_t3", "isResolved": True}},
                }
            }
        )

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_resolves_multiple_comments_in_two_calls(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
        comment_ids: list[str],
        batch_query_response: str,
        batch_mutation_response: str,
    ) -> None:
        mock_api.side_effect = [
            _completed(stdout=batch_query_response),
            _completed(stdout=batch_mutation_response),
        ]

        result = await gh.pr_comments(
            action="resolve",
            comment_ids=comment_ids,
        )

        assert mock_api.call_count == 2
        assert isinstance(result, SuccessResult)
        assert "r0" in result.value["data"]
        assert "r1" in result.value["data"]
        assert "r2" in result.value["data"]

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_batch_query_uses_aliased_nodes(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
        comment_ids: list[str],
        batch_query_response: str,
        batch_mutation_response: str,
    ) -> None:
        mock_api.side_effect = [
            _completed(stdout=batch_query_response),
            _completed(stdout=batch_mutation_response),
        ]

        await gh.pr_comments(action="resolve", comment_ids=comment_ids)

        query_call = mock_api.call_args_list[0]
        query_str = query_call.kwargs["fields"]["query"]
        assert "n0:" in query_str
        assert "n1:" in query_str
        assert "n2:" in query_str

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_comment_ids_takes_precedence_over_comment_id(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.side_effect = [
            _completed(
                stdout=json.dumps({"data": {"n0": {"pullRequestReviewThread": {"id": "PRRT_t1"}}}})
            ),
            _completed(
                stdout=json.dumps(
                    {"data": {"r0": {"thread": {"id": "PRRT_t1", "isResolved": True}}}}
                )
            ),
        ]

        await gh.pr_comments(
            action="resolve",
            comment_id="PRRC_ignored",
            comment_ids=["PRRC_used"],
        )

        query_str = mock_api.call_args_list[0].kwargs["fields"]["query"]
        assert '"PRRC_used"' in query_str
        assert "PRRC_ignored" not in query_str


class TestPrCommentsResolveErrors:
    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_returns_error_when_query_fails(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(
            returncode=1,
            stderr="GraphQL error",
        )

        result = await gh.pr_comments(
            action="resolve",
            comment_id="PRRC_abc",
        )

        assert isinstance(result, ErrorResult)
        assert result.error == "GraphQL error"

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_returns_error_when_thread_not_found(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(
            stdout=json.dumps({"data": {"n0": None}}),
        )

        result = await gh.pr_comments(
            action="resolve",
            comment_id="PRRC_bad",
        )

        assert isinstance(result, ErrorResult)
        assert "Could not find thread" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_returns_error_when_thread_id_invalid(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(
            stdout=json.dumps(
                {"data": {"n0": {"pullRequestReviewThread": {"id": "INVALID_123"}}}}
            ),
        )

        result = await gh.pr_comments(
            action="resolve",
            comment_id="PRRC_bad",
        )

        assert isinstance(result, ErrorResult)
        assert "Could not find thread" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_partial_failure_includes_warnings(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.side_effect = [
            _completed(
                stdout=json.dumps(
                    {
                        "data": {
                            "n0": {"pullRequestReviewThread": {"id": "PRRT_good"}},
                            "n1": None,
                        }
                    }
                )
            ),
            _completed(
                stdout=json.dumps(
                    {"data": {"r0": {"thread": {"id": "PRRT_good", "isResolved": True}}}}
                )
            ),
        ]

        result = await gh.pr_comments(
            action="resolve",
            comment_ids=["PRRC_good", "PRRC_bad"],
        )

        assert result.value["data"]["r0"]["thread"]["isResolved"] is True
        assert "warnings" in result.value
        assert any("PRRC_bad" in w for w in result.value["warnings"])

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_mutation_error_returns_error(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.side_effect = [
            _completed(
                stdout=json.dumps({"data": {"n0": {"pullRequestReviewThread": {"id": "PRRT_t1"}}}})
            ),
            _completed(returncode=1, stderr="Mutation failed"),
        ]

        result = await gh.pr_comments(
            action="resolve",
            comment_id="PRRC_abc",
        )

        assert isinstance(result, ErrorResult)
        assert result.error == "Mutation failed"


class TestResolveReviewThreadDirect:
    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_resolves_by_thread_ids(
        self,
        mock_api: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(
            stdout=json.dumps({"data": {"r0": {"thread": {"id": "PRRT_t1", "isResolved": True}}}}),
        )

        result = await gh.resolve_review_thread(thread_ids=["PRRT_t1"])

        assert isinstance(result, SuccessResult)
        assert result.value["data"]["r0"]["thread"]["isResolved"] is True
        assert mock_api.call_count == 1

    @pytest.mark.asyncio
    async def test_rejects_invalid_thread_ids(self) -> None:
        result = await gh.resolve_review_thread(thread_ids=["INVALID_123"])

        assert isinstance(result, ErrorResult)
        assert "must start with PRRT_" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_resolves_by_comment_ids(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.side_effect = [
            _completed(
                stdout=json.dumps({"data": {"n0": {"pullRequestReviewThread": {"id": "PRRT_t1"}}}})
            ),
            _completed(
                stdout=json.dumps(
                    {"data": {"r0": {"thread": {"id": "PRRT_t1", "isResolved": True}}}}
                )
            ),
        ]

        result = await gh.resolve_review_thread(comment_ids=["PRRC_abc"])

        assert isinstance(result, SuccessResult)
        assert mock_api.call_count == 2

    @pytest.mark.asyncio
    async def test_returns_error_when_no_ids(self) -> None:
        result = await gh.resolve_review_thread()

        assert isinstance(result, ErrorResult)
        assert "thread_ids" in result.error


class TestPrCommentListFilters:
    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_filters_by_review_id(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(
            stdout=json.dumps(
                [
                    {"id": 1, "pull_request_review_id": 100},
                    {"id": 2, "pull_request_review_id": 200},
                    {"id": 3, "pull_request_review_id": 100},
                ]
            ),
        )

        result = await gh.pr_comments(
            action="list",
            pr_number=42,
            review_id=100,
        )

        assert isinstance(result, SuccessResult)
        assert {c["id"] for c in result.value} == {1, 3}

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_returns_all_when_no_review_id(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(
            stdout=json.dumps(
                [
                    {"id": 1, "pull_request_review_id": 100},
                    {"id": 2, "pull_request_review_id": 200},
                ]
            ),
        )

        result = await gh.pr_comments(action="list", pr_number=42)

        assert isinstance(result, SuccessResult)
        assert len(result.value) == 2

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_unresolved_only_uses_graphql(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(
            stdout=json.dumps(
                {
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "reviewThreads": {
                                    "nodes": [
                                        {
                                            "id": "PRRT_1",
                                            "isResolved": False,
                                            "isOutdated": False,
                                            "comments": {
                                                "nodes": [
                                                    {
                                                        "databaseId": 11,
                                                        "body": "open",
                                                        "path": "a.py",
                                                        "line": 1,
                                                        "author": {"login": "alice"},
                                                        "pullRequestReview": {"databaseId": 100},
                                                    }
                                                ]
                                            },
                                        },
                                        {
                                            "id": "PRRT_2",
                                            "isResolved": True,
                                            "isOutdated": False,
                                            "comments": {
                                                "nodes": [
                                                    {
                                                        "databaseId": 22,
                                                        "body": "closed",
                                                        "path": "b.py",
                                                        "line": 2,
                                                        "author": {"login": "bob"},
                                                        "pullRequestReview": {"databaseId": 200},
                                                    }
                                                ]
                                            },
                                        },
                                    ]
                                }
                            }
                        }
                    }
                }
            ),
        )

        result = await gh.pr_comments(
            action="list",
            pr_number=42,
            unresolved_only=True,
        )

        assert isinstance(result, SuccessResult)
        assert result.value["count"] == 1
        assert result.value["unresolved_threads"][0]["thread_id"] == "PRRT_1"
        assert result.value["unresolved_threads"][0]["databaseId"] == 11
        # Verify the GraphQL endpoint was called, not the REST list
        assert mock_api.call_args.args[0] == "graphql"


class TestMinimizeComments:
    @pytest.fixture
    def batch_response(self) -> str:
        return json.dumps(
            {
                "data": {
                    "m0": {
                        "minimizedComment": {
                            "isMinimized": True,
                            "minimizedReason": "OUTDATED",
                        }
                    },
                    "m1": {
                        "minimizedComment": {
                            "isMinimized": True,
                            "minimizedReason": "OUTDATED",
                        }
                    },
                }
            }
        )

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_batches_into_single_request(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
        batch_response: str,
    ) -> None:
        mock_api.return_value = _completed(stdout=batch_response)

        result = await gh.minimize_comments(
            node_ids=["PRRC_a", "PRRC_b"],
        )

        assert isinstance(result, SuccessResult)
        assert mock_api.call_count == 1
        query = mock_api.call_args.kwargs["fields"]["query"]
        assert "m0: minimizeComment" in query
        assert "m1: minimizeComment" in query
        assert "classifier: OUTDATED" in query

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_accepts_alternate_classifier(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
        batch_response: str,
    ) -> None:
        mock_api.return_value = _completed(stdout=batch_response)

        result = await gh.minimize_comments(
            node_ids=["PRRC_a"],
            classifier="RESOLVED",
        )

        assert isinstance(result, SuccessResult)
        query = mock_api.call_args.kwargs["fields"]["query"]
        assert "classifier: RESOLVED" in query

    @pytest.mark.asyncio
    async def test_rejects_empty_node_ids(self) -> None:
        result = await gh.minimize_comments(node_ids=[])

        assert isinstance(result, ErrorResult)
        assert "node_ids required" in result.error

    @pytest.mark.asyncio
    async def test_rejects_invalid_classifier(self) -> None:
        result = await gh.minimize_comments(
            node_ids=["PRRC_a"],
            classifier="INVALID",
        )

        assert isinstance(result, ErrorResult)
        assert "Invalid classifier" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_returns_error_on_api_failure(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(returncode=1, stderr="Forbidden")

        result = await gh.minimize_comments(node_ids=["PRRC_a"])

        assert isinstance(result, ErrorResult)
        assert "Forbidden" in result.error


class TestResolveRepo:
    @pytest.mark.asyncio
    async def test_returns_repository_ref(self) -> None:
        with patch.object(gh, "_detect_repo", new_callable=AsyncMock, return_value="owner/repo"):
            result = await gh._resolve_repo(None)

        assert isinstance(result, SuccessResult)
        assert result.value.owner == "owner"
        assert result.value.name == "repo"


class TestPrCommentReply:
    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_posts_reply(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(
            stdout=json.dumps({"id": 999, "body": "reply text"}),
        )

        result = await gh.pr_comment_reply(
            pr_number=42,
            comment_id=123,
            body="reply text",
        )

        assert isinstance(result, SuccessResult)
        mock_api.assert_called_once()
        call_kwargs = mock_api.call_args.kwargs
        assert call_kwargs["method"] == "POST"
        assert call_kwargs["fields"]["body"] == "reply text"
        assert call_kwargs["fields"]["in_reply_to"] == 123

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_returns_error_on_api_failure(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(
            returncode=1,
            stderr="Not Found",
        )

        result = await gh.pr_comment_reply(
            pr_number=42,
            comment_id=123,
            body="text",
        )

        assert isinstance(result, ErrorResult)

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_coerces_numeric_string_comment_id_to_int(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(stdout=json.dumps({"id": 1}))

        result = await gh.pr_comment_reply(
            pr_number=42,
            comment_id="3130499018",  # type: ignore[arg-type]
            body="text",
        )

        assert isinstance(result, SuccessResult)
        assert mock_api.call_args.kwargs["fields"]["in_reply_to"] == 3130499018

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_rejects_non_numeric_comment_id(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        result = await gh.pr_comment_reply(
            pr_number=42,
            comment_id="PRRC_abc",  # type: ignore[arg-type]
            body="text",
        )

        assert isinstance(result, ErrorResult)
        assert "must be an integer" in result.error
        assert mock_api.call_count == 0


class TestPrCommentsActionReply:
    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_coerces_numeric_string_to_int(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(stdout=json.dumps({"id": 1}))

        result = await gh.pr_comments(
            action="reply",
            pr_number=42,
            comment_id="3130499018",
            body="text",
        )

        assert isinstance(result, SuccessResult)
        assert mock_api.call_args.kwargs["fields"]["in_reply_to"] == 3130499018

    @pytest.mark.asyncio
    async def test_rejects_non_numeric_comment_id(
        self,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        result = await gh.pr_comments(
            action="reply",
            pr_number=42,
            comment_id="PRRC_abc",
            body="text",
        )

        assert isinstance(result, ErrorResult)
        assert "must be an integer" in result.error


class TestRequestReview:
    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_requests_user_reviewers(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(
            stdout=json.dumps({"requested_reviewers": [{"login": "alice"}]}),
        )

        result = await gh.request_review(
            pr_number=42,
            reviewers=["alice"],
        )

        assert isinstance(result, SuccessResult)
        fields = mock_api.call_args.kwargs["fields"]
        assert fields["reviewers"] == ["alice"]

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_requests_team_reviewers(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(
            stdout=json.dumps({"requested_teams": [{"slug": "backend"}]}),
        )

        result = await gh.request_review(
            pr_number=42,
            reviewers=["org/backend"],
            team=True,
        )

        assert isinstance(result, SuccessResult)
        fields = mock_api.call_args.kwargs["fields"]
        assert fields["team_reviewers"] == ["backend"]


class TestPrCommentsStrategyDispatch:
    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(
        self,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        result = await gh.pr_comments(action="invalid")

        assert isinstance(result, ErrorResult)
        assert "Unknown action" in result.error
        assert "get, list, reply, resolve" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_get_action_requires_comment_id(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        result = await gh.pr_comments(action="get")

        assert isinstance(result, ErrorResult)
        assert "comment_id required" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_list_action_requires_pr_number(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        result = await gh.pr_comments(action="list")

        assert isinstance(result, ErrorResult)
        assert "pr_number required" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_get_action_fetches_comment(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(
            stdout=json.dumps({"id": 42, "body": "comment"}),
        )

        result = await gh.pr_comments(action="get", comment_id=42)

        assert isinstance(result, SuccessResult)

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_list_action_fetches_comments(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(
            stdout=json.dumps([{"id": 1}, {"id": 2}]),
        )

        result = await gh.pr_comments(action="list", pr_number=10)

        assert isinstance(result, SuccessResult)

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_reply_action_posts_comment(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(
            stdout=json.dumps({"id": 99, "body": "thanks"}),
        )

        result = await gh.pr_comments(
            action="reply",
            pr_number=10,
            comment_id=5,
            body="thanks",
        )

        assert isinstance(result, SuccessResult)

    @pytest.mark.asyncio
    async def test_explicit_repo_param(self) -> None:
        result = await gh._resolve_repo("my-org/my-repo")

        assert isinstance(result, SuccessResult)
        assert result.value == RepositoryRef(owner="my-org", name="my-repo")

    @pytest.mark.asyncio
    async def test_returns_error_when_no_repo(self) -> None:
        with patch.object(gh, "_detect_repo", new_callable=AsyncMock, return_value=None):
            result = await gh._resolve_repo(None)

        assert isinstance(result, ErrorResult)
        assert "repository" in result.error.lower()

    @pytest.mark.asyncio
    async def test_returns_error_for_invalid_format(self) -> None:
        result = await gh._resolve_repo("invalid-repo-no-slash")

        assert isinstance(result, ErrorResult)
        assert "Invalid repository reference" in result.error


class TestUpdatePr:
    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_updates_body(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(stdout="{}")

        result = await gh.update_pr(pr_number=42, body="new body")

        assert isinstance(result, SuccessResult)
        assert result.value == {
            "pr_number": 42,
            "url": "https://github.com/owner/repo/pull/42",
        }
        mock_api.assert_awaited_once()
        call = mock_api.call_args
        assert call.args[0] == "repos/owner/repo/pulls/42"
        assert call.kwargs["method"] == "PATCH"
        assert call.kwargs["fields"] == {"body": "new body"}

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_updates_title_and_base(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(stdout="{}")

        result = await gh.update_pr(
            pr_number=7,
            title="New title",
            base_branch="main",
        )

        assert isinstance(result, SuccessResult)
        assert mock_api.call_args.kwargs["fields"] == {
            "title": "New title",
            "base": "main",
        }

    @pytest.mark.asyncio
    async def test_returns_error_when_no_fields_provided(self) -> None:
        result = await gh.update_pr(pr_number=1)

        assert isinstance(result, ErrorResult)
        assert "at least one" in result.error.lower()

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_returns_error_when_repo_unresolved(
        self,
        mock_api: AsyncMock,
    ) -> None:
        with patch.object(gh, "_detect_repo", new_callable=AsyncMock, return_value=None):
            result = await gh.update_pr(pr_number=1, body="x")

        assert isinstance(result, ErrorResult)
        mock_api.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_returns_error_on_api_failure(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(returncode=1, stderr="HTTP 422: Validation Failed")

        result = await gh.update_pr(pr_number=42, body="x")

        assert isinstance(result, ErrorResult)
        assert "422" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_uses_explicit_repo_when_provided(
        self,
        mock_api: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(stdout="{}")

        result = await gh.update_pr(
            pr_number=99,
            body="x",
            repo="other/proj",
        )

        assert isinstance(result, SuccessResult)
        assert result.value["url"] == "https://github.com/other/proj/pull/99"
        assert mock_api.call_args.args[0] == "repos/other/proj/pulls/99"
