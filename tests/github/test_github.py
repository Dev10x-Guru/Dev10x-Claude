from __future__ import annotations

import json
import subprocess
from unittest.mock import AsyncMock, patch

import pytest

from dev10x.domain.common.repository_ref import RepositoryRef
from dev10x.domain.common.result import ErrorResult, SuccessResult, ok

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


def _thread_lookup_response(
    alias: str,
    db_id: int,
    thread_id: str,
) -> dict:
    """Build the new-style query response for _pr_comment_resolve (GH-329).

    The query fetches databaseId and reviewThreads on the parent PR,
    then matches the thread whose first comment has the same databaseId.
    """
    return {
        "data": {
            alias: {
                "databaseId": db_id,
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": [
                            {
                                "id": thread_id,
                                "comments": {"nodes": [{"databaseId": db_id}]},
                            }
                        ]
                    }
                },
            }
        }
    }


class TestPrCommentsResolveSingle:
    @pytest.fixture
    def query_response(self) -> str:
        return json.dumps(_thread_lookup_response("n0", db_id=111, thread_id="PRRT_thread123"))

    @pytest.fixture
    def mutation_response(self) -> str:
        return json.dumps(
            {"data": {"r0": {"thread": {"id": "PRRT_thread123", "isResolved": True}}}}
        )

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
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
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_query_uses_database_id_lookup(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
        query_response: str,
        mutation_response: str,
    ) -> None:
        """Query must use databaseId+reviewThreads, not pullRequestReviewThread (GH-329)."""
        mock_api.side_effect = [
            _completed(stdout=query_response),
            _completed(stdout=mutation_response),
        ]

        await gh.pr_comments(action="resolve", comment_id="PRRC_comment123")

        query_call = mock_api.call_args_list[0]
        query_str = query_call.kwargs["fields"]["query"]
        assert "databaseId" in query_str
        assert "reviewThreads" in query_str
        assert "pullRequestReviewThread" not in query_str

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
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
        def _node(db_id: int, thread_id: str) -> dict:
            return {
                "databaseId": db_id,
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": [
                            {
                                "id": thread_id,
                                "comments": {"nodes": [{"databaseId": db_id}]},
                            }
                        ]
                    }
                },
            }

        return json.dumps(
            {
                "data": {
                    "n0": _node(101, "PRRT_t1"),
                    "n1": _node(102, "PRRT_t2"),
                    "n2": _node(103, "PRRT_t3"),
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
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
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
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
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
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_comment_ids_takes_precedence_over_comment_id(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.side_effect = [
            _completed(
                stdout=json.dumps(_thread_lookup_response("n0", db_id=99, thread_id="PRRT_t1"))
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
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
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
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
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
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_returns_error_when_no_matching_thread(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        # databaseId 42 is returned, but reviewThreads has a different databaseId
        mock_api.return_value = _completed(
            stdout=json.dumps(
                {
                    "data": {
                        "n0": {
                            "databaseId": 42,
                            "pullRequest": {
                                "reviewThreads": {
                                    "nodes": [
                                        {
                                            "id": "PRRT_other",
                                            "comments": {"nodes": [{"databaseId": 999}]},
                                        }
                                    ]
                                }
                            },
                        }
                    }
                }
            ),
        )

        result = await gh.pr_comments(
            action="resolve",
            comment_id="PRRC_bad",
        )

        assert isinstance(result, ErrorResult)
        assert "Could not find thread" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
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
                            "n0": {
                                "databaseId": 55,
                                "pullRequest": {
                                    "reviewThreads": {
                                        "nodes": [
                                            {
                                                "id": "PRRT_good",
                                                "comments": {"nodes": [{"databaseId": 55}]},
                                            }
                                        ]
                                    }
                                },
                            },
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
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_mutation_error_returns_error(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.side_effect = [
            _completed(
                stdout=json.dumps(_thread_lookup_response("n0", db_id=77, thread_id="PRRT_t1"))
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
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
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
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_resolves_by_comment_ids(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.side_effect = [
            _completed(
                stdout=json.dumps(_thread_lookup_response("n0", db_id=88, thread_id="PRRT_t1"))
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
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
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
        # ADR-0009: list payloads are wrapped under "value" to satisfy the
        # Mapping contract; the {"value": [...]} wire shape is unchanged.
        assert {c["id"] for c in result.value["value"]} == {1, 3}

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
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
        assert len(result.value["value"]) == 2

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_non_json_output_passes_through_as_dict(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        # When gh returns non-JSON, _parse_gh_api_result yields a
        # {"raw_output": ...} dict; _pr_comment_list passes that dict
        # through unwrapped (ADR-0009 Mapping contract already met).
        mock_api.return_value = _completed(stdout="not json")

        result = await gh.pr_comments(action="list", pr_number=42)

        assert isinstance(result, SuccessResult)
        assert result.value == {"raw_output": "not json"}

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
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
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
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
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
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
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
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
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
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
        assert call_kwargs["as_bot"] is True
        assert call_kwargs["repo"] == "owner/repo"

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
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
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
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
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
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


class TestPrIssueComment:
    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_posts_top_level_comment(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(
            stdout=json.dumps({"id": 4468, "body": "bundle reply"}),
        )

        result = await gh.pr_issue_comment(
            pr_number=203,
            body="bundle reply",
        )

        assert isinstance(result, SuccessResult)
        endpoint = mock_api.call_args.args[0]
        assert endpoint == "repos/owner/repo/issues/203/comments"
        call_kwargs = mock_api.call_args.kwargs
        assert call_kwargs["method"] == "POST"
        assert call_kwargs["fields"] == {"body": "bundle reply"}
        assert "in_reply_to" not in call_kwargs["fields"]
        assert call_kwargs["as_bot"] is True
        assert call_kwargs["repo"] == "owner/repo"

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_returns_error_on_api_failure(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(
            returncode=1,
            stderr="Not Found",
        )

        result = await gh.pr_issue_comment(
            pr_number=203,
            body="body",
        )

        assert isinstance(result, ErrorResult)


class TestPrCommentsActionReply:
    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
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
        assert mock_api.call_args.kwargs["as_bot"] is True
        assert mock_api.call_args.kwargs["repo"] == "owner/repo"

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


class TestPrCommentsActionEdit:
    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_patches_comment_body(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(
            stdout=json.dumps({"id": 3130499018, "body": "refreshed"}),
        )

        result = await gh.pr_comments(
            action="edit",
            comment_id=3130499018,
            body="refreshed",
        )

        assert isinstance(result, SuccessResult)
        assert mock_api.call_args.args[0] == ("repos/owner/repo/pulls/comments/3130499018")
        assert mock_api.call_args.kwargs["method"] == "PATCH"
        assert mock_api.call_args.kwargs["fields"] == {"body": "refreshed"}
        assert mock_api.call_args.kwargs["as_bot"] is True

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_coerces_numeric_string_to_int(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(stdout=json.dumps({"id": 1}))

        result = await gh.pr_comments(
            action="edit",
            comment_id="3130499018",
            body="refreshed",
        )

        assert isinstance(result, SuccessResult)
        assert mock_api.call_args.args[0] == ("repos/owner/repo/pulls/comments/3130499018")

    @pytest.mark.asyncio
    async def test_rejects_non_numeric_comment_id(
        self,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        result = await gh.pr_comments(
            action="edit",
            comment_id="PRRC_abc",
            body="refreshed",
        )

        assert isinstance(result, ErrorResult)
        assert "must be an integer" in result.error

    @pytest.mark.asyncio
    async def test_requires_comment_id_and_body(
        self,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        result = await gh.pr_comments(action="edit")

        assert isinstance(result, ErrorResult)
        assert "comment_id and body required" in result.error


class TestRequestReview:
    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
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
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
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
        assert "get, list, reply, edit, resolve" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_get_action_requires_comment_id(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        result = await gh.pr_comments(action="get")

        assert isinstance(result, ErrorResult)
        assert "comment_id required" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_list_action_requires_pr_number(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        result = await gh.pr_comments(action="list")

        assert isinstance(result, ErrorResult)
        assert "pr_number required" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
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
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
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
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
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


class TestMilestoneClose:
    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_closes_milestone(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(stdout="{}")

        result = await gh.milestone_close(number=38)

        assert isinstance(result, SuccessResult)
        assert result.value == {
            "number": 38,
            "state": "closed",
            "url": "https://github.com/owner/repo/milestone/38",
        }
        call = mock_api.call_args
        assert call.args[0] == "repos/owner/repo/milestones/38"
        assert call.kwargs["method"] == "PATCH"
        assert call.kwargs["fields"] == {"state": "closed"}

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_returns_error_when_repo_unresolved(
        self,
        mock_api: AsyncMock,
    ) -> None:
        with patch.object(gh, "_detect_repo", new_callable=AsyncMock, return_value=None):
            result = await gh.milestone_close(number=1)

        assert isinstance(result, ErrorResult)
        mock_api.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_returns_error_on_api_failure(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(returncode=1, stderr="HTTP 403")

        result = await gh.milestone_close(number=5)

        assert isinstance(result, ErrorResult)
        assert "403" in result.error


class TestMilestoneCreate:
    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_creates_milestone(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(
            stdout=json.dumps({"number": 7, "title": "M3: Cleanup"})
        )

        result = await gh.milestone_create(title="M3: Cleanup", description="desc")

        assert isinstance(result, SuccessResult)
        assert result.value == {
            "number": 7,
            "title": "M3: Cleanup",
            "url": "https://github.com/owner/repo/milestone/7",
        }
        call = mock_api.call_args
        assert call.args[0] == "repos/owner/repo/milestones"
        assert call.kwargs["method"] == "POST"
        assert call.kwargs["fields"]["title"] == "M3: Cleanup"
        assert call.kwargs["fields"]["description"] == "desc"

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_returns_error_on_api_failure(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(returncode=1, stderr="HTTP 422: duplicate")

        result = await gh.milestone_create(title="M1")

        assert isinstance(result, ErrorResult)
        assert "422" in result.error


class TestIssueEdit:
    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_edits_title(
        self,
        mock_run: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="https://github.com/owner/repo/issues/42")

        result = await gh.issue_edit(number=42, title="New title", repo="owner/repo")

        assert isinstance(result, SuccessResult)
        assert result.value["number"] == 42
        assert result.value["url"] == "https://github.com/owner/repo/issues/42"
        args_called = mock_run.call_args.kwargs["args"]
        assert args_called[:5] == ["gh", "issue", "edit", "42", "--title"]
        assert "New title" in args_called

    @pytest.mark.asyncio
    async def test_requires_at_least_one_field(self) -> None:
        result = await gh.issue_edit(number=1)
        assert isinstance(result, ErrorResult)
        assert "at least one of" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="not found")

        result = await gh.issue_edit(number=99, title="x")

        assert isinstance(result, ErrorResult)
        assert "not found" in result.error


class TestIssueComment:
    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_posts_comment(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(
            stdout="https://github.com/owner/repo/issues/1#issuecomment-99"
        )

        result = await gh.issue_comment(number=1, body="thanks!", repo="owner/repo")

        assert isinstance(result, SuccessResult)
        assert result.value["url"].endswith("issuecomment-99")
        args_called = mock_run.call_args.kwargs["args"]
        assert args_called[:4] == ["gh", "issue", "comment", "1"]
        assert "--body-file" in args_called

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="auth required")

        result = await gh.issue_comment(number=1, body="hi")

        assert isinstance(result, ErrorResult)


class TestIssueCommentEdit:
    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_edits_comment(
        self,
        mock_run: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(
            stdout=json.dumps(
                {
                    "id": 99,
                    "body": "updated body",
                    "html_url": "https://github.com/owner/repo/issues/1#issuecomment-99",
                }
            )
        )

        result = await gh.issue_comment_edit(
            comment_id=99,
            body="updated body",
            repo="owner/repo",
        )

        assert isinstance(result, SuccessResult)
        assert result.value["id"] == 99
        assert result.value["body"] == "updated body"
        assert result.value["html_url"].endswith("issuecomment-99")
        args_called = mock_run.call_args.kwargs["args"]
        assert args_called[:5] == ["gh", "api", "-X", "PATCH", "-F"]
        assert args_called[-1] == "/repos/owner/repo/issues/comments/99"

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_returns_error_when_repo_missing(
        self,
        mock_run: AsyncMock,
    ) -> None:
        with patch.object(
            gh,
            "_resolve_repo",
            new_callable=AsyncMock,
            return_value=ErrorResult(error="no repo"),
        ):
            result = await gh.issue_comment_edit(comment_id=99, body="x")

        assert isinstance(result, ErrorResult)
        assert "no repo" in result.error
        mock_run.assert_not_called()

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_returns_error_on_api_failure(
        self,
        mock_run: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="404 Not Found")

        result = await gh.issue_comment_edit(comment_id=99, body="x", repo="owner/repo")

        assert isinstance(result, ErrorResult)
        assert "Not Found" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_returns_error_on_invalid_json(
        self,
        mock_run: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="not json")

        result = await gh.issue_comment_edit(comment_id=99, body="x", repo="owner/repo")

        assert isinstance(result, ErrorResult)
        assert "Invalid JSON" in result.error


class TestIssueCommentDelete:
    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_deletes_comment(
        self,
        mock_run: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="")

        result = await gh.issue_comment_delete(comment_id=99, repo="owner/repo")

        assert isinstance(result, SuccessResult)
        assert result.value == {"deleted": True, "comment_id": 99}
        args_called = mock_run.call_args.kwargs["args"]
        assert args_called == [
            "gh",
            "api",
            "-X",
            "DELETE",
            "/repos/owner/repo/issues/comments/99",
        ]

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_returns_error_when_repo_missing(
        self,
        mock_run: AsyncMock,
    ) -> None:
        with patch.object(
            gh,
            "_resolve_repo",
            new_callable=AsyncMock,
            return_value=ErrorResult(error="no repo"),
        ):
            result = await gh.issue_comment_delete(comment_id=99)

        assert isinstance(result, ErrorResult)
        mock_run.assert_not_called()

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_returns_error_on_api_failure(
        self,
        mock_run: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="403 Forbidden")

        result = await gh.issue_comment_delete(comment_id=99, repo="owner/repo")

        assert isinstance(result, ErrorResult)
        assert "Forbidden" in result.error


class TestIssueList:
    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_lists_issues(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(
            stdout=json.dumps(
                [
                    {
                        "number": 1,
                        "title": "Bug",
                        "labels": [],
                        "milestone": None,
                        "state": "OPEN",
                        "url": "u",
                    },
                ]
            )
        )

        result = await gh.issue_list(state="open", limit=5)

        assert isinstance(result, SuccessResult)
        assert len(result.value["issues"]) == 1
        assert result.value["issues"][0]["number"] == 1
        args_called = mock_run.call_args.kwargs["args"]
        assert "--state" in args_called
        assert "--limit" in args_called
        assert "--json" in args_called

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_filters_by_milestone_and_labels(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="[]")

        await gh.issue_list(milestone="M3", labels=["bug", "regression"])

        args_called = mock_run.call_args.kwargs["args"]
        assert "--milestone" in args_called
        assert args_called.count("--label") == 2
        assert "bug" in args_called and "regression" in args_called

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="rate limit")

        result = await gh.issue_list()

        assert isinstance(result, ErrorResult)


class TestUpdatePr:
    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
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
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
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
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_returns_error_when_repo_unresolved(
        self,
        mock_api: AsyncMock,
    ) -> None:
        with patch.object(gh, "_detect_repo", new_callable=AsyncMock, return_value=None):
            result = await gh.update_pr(pr_number=1, body="x")

        assert isinstance(result, ErrorResult)
        mock_api.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
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
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
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


class TestGhApiBotIdentity:
    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    @patch("dev10x.github.get_bot_token", new_callable=AsyncMock)
    async def test_swaps_env_when_as_bot_and_token_available(
        self,
        mock_token: AsyncMock,
        mock_run: AsyncMock,
    ) -> None:
        mock_token.return_value = "ghs_bot_token"
        mock_run.return_value = _completed(stdout="{}")

        await gh._gh_api(
            "repos/x/y/pulls/1/comments",
            method="POST",
            fields={"body": "hi"},
            repo="x/y",
            as_bot=True,
        )

        env = mock_run.call_args.kwargs["env"]
        assert env is not None
        assert env["GH_TOKEN"] == "ghs_bot_token"
        assert env["GITHUB_TOKEN"] == "ghs_bot_token"

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    @patch("dev10x.github.get_bot_token", new_callable=AsyncMock)
    async def test_falls_back_to_user_auth_when_token_unavailable(
        self,
        mock_token: AsyncMock,
        mock_run: AsyncMock,
    ) -> None:
        mock_token.return_value = None
        mock_run.return_value = _completed(stdout="{}")

        await gh._gh_api(
            "repos/x/y/pulls/1/comments",
            method="POST",
            repo="x/y",
            as_bot=True,
        )

        assert mock_run.call_args.kwargs["env"] is None

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    @patch("dev10x.github.AppConfig.load")
    @patch("dev10x.github.get_bot_token", new_callable=AsyncMock)
    async def test_warns_when_app_configured_but_token_exchange_fails(
        self,
        mock_token: AsyncMock,
        mock_load: AsyncMock,
        mock_run: AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_token.return_value = None
        mock_load.return_value = object()
        mock_run.return_value = _completed(stdout="{}")

        with caplog.at_level("WARNING", logger="dev10x.github"):
            await gh._gh_api(
                "repos/x/y/pulls/1/comments",
                repo="x/y",
                as_bot=True,
            )

        assert any("bot token exchange failed" in r.message for r in caplog.records), (
            f"Expected warning when App configured but exchange fails; got {caplog.records}"
        )

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    @patch("dev10x.github.AppConfig.load")
    @patch("dev10x.github.get_bot_token", new_callable=AsyncMock)
    async def test_silent_when_app_not_configured(
        self,
        mock_token: AsyncMock,
        mock_load: AsyncMock,
        mock_run: AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_token.return_value = None
        mock_load.return_value = None
        mock_run.return_value = _completed(stdout="{}")

        with caplog.at_level("WARNING", logger="dev10x.github"):
            await gh._gh_api(
                "repos/x/y/pulls/1/comments",
                repo="x/y",
                as_bot=True,
            )

        assert not any("bot token exchange failed" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    @patch("dev10x.github.get_bot_token", new_callable=AsyncMock)
    async def test_does_not_call_token_resolver_when_not_as_bot(
        self,
        mock_token: AsyncMock,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="{}")

        await gh._gh_api("repos/x/y/issues/1", repo="x/y", as_bot=False)

        assert mock_token.call_count == 0
        assert mock_run.call_args.kwargs["env"] is None

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    @patch("dev10x.github.get_bot_token", new_callable=AsyncMock)
    async def test_does_not_call_token_resolver_without_repo(
        self,
        mock_token: AsyncMock,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="{}")

        await gh._gh_api("rate_limit", as_bot=True)

        assert mock_token.call_count == 0


class TestPostSummaryComment:
    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    @patch("dev10x.github._bot_env", new_callable=AsyncMock, return_value=None)
    @patch("dev10x.github._detect_repo", new_callable=AsyncMock, return_value="owner/repo")
    async def test_posts_summary_successfully(
        self,
        _mock_repo: AsyncMock,
        _mock_bot_env: AsyncMock,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="Comment posted")

        result = await gh.post_summary_comment(
            issue_id="GH-79",
            summary_text="- Did the thing\n- And another",
        )

        assert isinstance(result, SuccessResult)
        assert result.value == {"success": True, "output": "Comment posted"}
        called_args = mock_run.call_args.args
        assert "GH-79" in called_args
        assert "- Did the thing\n- And another" in called_args

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    @patch("dev10x.github._bot_env", new_callable=AsyncMock)
    @patch("dev10x.github._detect_repo", new_callable=AsyncMock, return_value="owner/repo")
    async def test_passes_bot_env_when_available(
        self,
        _mock_repo: AsyncMock,
        mock_bot_env: AsyncMock,
        mock_run: AsyncMock,
    ) -> None:
        mock_bot_env.return_value = {
            "GH_TOKEN": "ghs_bot",
            "GITHUB_TOKEN": "ghs_bot",
        }
        mock_run.return_value = _completed(stdout="ok")

        await gh.post_summary_comment(issue_id="GH-1", summary_text="x")

        env_vars = mock_run.call_args.kwargs.get("env_vars")
        assert env_vars is not None
        assert env_vars["GH_TOKEN"] == "ghs_bot"

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    @patch("dev10x.github._bot_env", new_callable=AsyncMock, return_value=None)
    @patch("dev10x.github._detect_repo", new_callable=AsyncMock, return_value="owner/repo")
    async def test_returns_error_on_script_failure(
        self,
        _mock_repo: AsyncMock,
        _mock_bot_env: AsyncMock,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="API rate limit")

        result = await gh.post_summary_comment(issue_id="GH-1", summary_text="x")

        assert isinstance(result, ErrorResult)
        assert "rate limit" in result.error


class TestCreatePr:
    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_creates_pr_and_parses_number_and_url(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(
            stdout="https://github.com/owner/repo/pull/42\n42",
        )

        result = await gh.create_pr(
            title="My PR",
            job_story="When ... I want to ... so ... can ...",
            issue_id="GH-79",
            fixes_url="https://github.com/owner/repo/issues/79",
        )

        assert isinstance(result, SuccessResult)
        assert result.value["pr_number"] == 42
        assert result.value["url"] == "https://github.com/owner/repo/pull/42"

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_passes_blank_fixes_url_and_base_when_omitted(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="https://github.com/o/r/pull/1\n1")

        await gh.create_pr(
            title="t",
            job_story="js",
            issue_id="GH-1",
        )

        called_args = mock_run.call_args.args
        # Trailing args: fixes_url, base_branch, closes_csv, draft
        assert called_args[-4:] == ("", "", "", "true")

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_emits_closes_csv_and_draft_false(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="https://github.com/o/r/pull/9\n9")

        await gh.create_pr(
            title="t",
            job_story="js",
            issue_id="GH-1",
            closes=[184, 185, 186],
            draft=False,
        )

        called_args = mock_run.call_args.args
        assert called_args[-2:] == ("184,185,186", "false")

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_falls_back_to_synthetic_url_when_stdout_lacks_http(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="99")

        result = await gh.create_pr(title="t", job_story="js", issue_id="GH-1")

        assert isinstance(result, SuccessResult)
        assert result.value == {"pr_number": 99, "url": "PR #99"}

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_returns_error_on_script_failure(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="branch not pushed")

        result = await gh.create_pr(title="t", job_story="js", issue_id="GH-1")

        assert isinstance(result, ErrorResult)
        assert "branch not pushed" in result.error


class TestMergePr:
    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_merges_pr_with_defaults(
        self,
        mock_run: AsyncMock,
        mock_resolve_repo,
    ) -> None:
        mock_run.return_value = _completed(stdout="merged\n")

        result = await gh.merge_pr(pr_number=42)

        assert isinstance(result, SuccessResult)
        assert result.value == {
            "pr_number": 42,
            "url": "https://github.com/owner/repo/pull/42",
            "strategy": "rebase",
            "branch_deleted": True,
            "repo": "owner/repo",
        }
        called_args = mock_run.call_args.kwargs["args"]
        assert called_args == [
            "gh",
            "pr",
            "merge",
            "42",
            "--repo",
            "owner/repo",
            "--rebase",
            "--delete-branch",
        ]

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_squash_strategy_without_delete_branch(
        self,
        mock_run: AsyncMock,
        mock_resolve_repo,
    ) -> None:
        mock_run.return_value = _completed()

        result = await gh.merge_pr(
            pr_number=7,
            strategy="squash",
            delete_branch=False,
        )

        assert isinstance(result, SuccessResult)
        assert result.value["strategy"] == "squash"
        assert result.value["branch_deleted"] is False
        called_args = mock_run.call_args.kwargs["args"]
        assert "--squash" in called_args
        assert "--delete-branch" not in called_args

    @pytest.mark.asyncio
    async def test_rejects_invalid_strategy(self) -> None:
        result = await gh.merge_pr(pr_number=1, strategy="bogus")

        assert isinstance(result, ErrorResult)
        assert "Invalid merge strategy" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_returns_error_on_gh_failure(
        self,
        mock_run: AsyncMock,
        mock_resolve_repo,
    ) -> None:
        mock_run.return_value = _completed(
            returncode=1,
            stderr="Pull request is not mergeable",
        )

        result = await gh.merge_pr(pr_number=42)

        assert isinstance(result, ErrorResult)
        assert "not mergeable" in result.error


class TestGenerateCommitList:
    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_returns_commit_list_on_success(
        self,
        mock_run: AsyncMock,
    ) -> None:
        commit_list = "- abc1234 First commit\n- def5678 Second commit"
        mock_run.return_value = _completed(stdout=commit_list + "\n")

        result = await gh.generate_commit_list(pr_number=42)

        assert isinstance(result, SuccessResult)
        assert result.value == {"commit_list": commit_list}

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_passes_base_branch_when_supplied(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="")

        await gh.generate_commit_list(pr_number=42, base_branch="main")

        called_args = mock_run.call_args.args
        assert "42" in called_args
        assert "main" in called_args

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_returns_error_on_script_failure(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="no commits")

        result = await gh.generate_commit_list(pr_number=42)

        assert isinstance(result, ErrorResult)
        assert "no commits" in result.error


class TestPrGet:
    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_parses_pr_json(self, mock_run: AsyncMock) -> None:
        # ``merged`` was removed from gh-pr-get.sh (GH-329).
        # Derive merged-ness from state == "MERGED" or mergedAt != null.
        mock_run.return_value = _completed(
            stdout=json.dumps(
                {
                    "number": 42,
                    "title": "Fix things",
                    "state": "OPEN",
                    "mergedAt": None,
                    "url": "https://github.com/owner/repo/pull/42",
                }
            )
        )

        result = await gh.pr_get(number=42, repo="owner/repo")

        assert isinstance(result, SuccessResult)
        assert result.value["number"] == 42
        assert result.value["state"] == "OPEN"
        assert "merged" not in result.value
        called_args = mock_run.call_args.args
        assert "skills/gh-context/scripts/gh-pr-get.sh" in called_args[0]
        assert "42" in called_args
        assert "owner/repo" in called_args

    def test_gh_pr_get_script_excludes_merged_field(self) -> None:
        """gh-pr-get.sh must not request the invalid ``merged`` JSON field (GH-329)."""
        from pathlib import Path

        script_path = (
            Path(__file__).parents[2] / "skills" / "gh-context" / "scripts" / "gh-pr-get.sh"
        )
        content = script_path.read_text()
        assert "merged," not in content
        # ",mergedAt" is valid; assert the standalone ",merged" field is absent
        assert ",merged," not in content
        assert ",merged\n" not in content
        # mergedAt is the valid replacement field
        assert "mergedAt" in content

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_returns_error_on_script_failure(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="not found")

        result = await gh.pr_get(number=999)

        assert isinstance(result, ErrorResult)
        assert "not found" in result.error


class TestIssueClose:
    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_closes_with_default_reason(
        self,
        mock_run: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="")

        result = await gh.issue_close(number=42, repo="owner/repo")

        assert isinstance(result, SuccessResult)
        assert result.value == {
            "number": 42,
            "state": "closed",
            "url": "https://github.com/owner/repo/issues/42",
        }
        called_args = mock_run.call_args.kwargs["args"]
        assert called_args[:6] == [
            "gh",
            "issue",
            "close",
            "42",
            "--reason",
            "completed",
        ]

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_accepts_not_planned_reason(
        self,
        mock_run: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="")

        result = await gh.issue_close(number=1, reason="not_planned", repo="owner/repo")

        assert isinstance(result, SuccessResult)
        called_args = mock_run.call_args.kwargs["args"]
        assert "not_planned" in called_args

    @pytest.mark.asyncio
    async def test_rejects_invalid_reason(self) -> None:
        result = await gh.issue_close(number=1, reason="abandoned")

        assert isinstance(result, ErrorResult)
        assert "completed" in result.error and "not_planned" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_passes_comment_when_provided(
        self,
        mock_run: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="")

        result = await gh.issue_close(
            number=7,
            comment="Done — see PR #99",
            repo="owner/repo",
        )

        assert isinstance(result, SuccessResult)
        called_args = mock_run.call_args.kwargs["args"]
        assert "--comment" in called_args
        assert "Done — see PR #99" in called_args

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="not found")

        result = await gh.issue_close(number=999)

        assert isinstance(result, ErrorResult)
        assert "not found" in result.error


class TestIssueReopen:
    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_reopens_issue(
        self,
        mock_run: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="")

        result = await gh.issue_reopen(number=42, repo="owner/repo")

        assert isinstance(result, SuccessResult)
        assert result.value == {
            "number": 42,
            "state": "open",
            "url": "https://github.com/owner/repo/issues/42",
        }
        called_args = mock_run.call_args.kwargs["args"]
        assert called_args[:4] == ["gh", "issue", "reopen", "42"]

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="not found")

        result = await gh.issue_reopen(number=999)

        assert isinstance(result, ErrorResult)
        assert "not found" in result.error
