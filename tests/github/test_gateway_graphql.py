"""_graphql: one place that checks a GraphQL response (GH-1857)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from dev10x.domain.common.repository_ref import RepositoryRef
from dev10x.domain.common.result import ErrorResult, SuccessResult

from dev10x.core.github import _gateway
from tests.fakers.process import completed as _completed


async def _run(*, response: Any) -> Any:
    with patch.object(
        _gateway, "_gh_api_raw", new_callable=AsyncMock, return_value=response
    ) as raw:
        result = await _gateway._graphql("query { viewer { login } }")
    raw.assert_awaited_once_with("graphql", fields={"query": "query { viewer { login } }"})
    return result


class TestGraphql:
    @pytest.mark.asyncio
    async def test_returns_the_data_object(self) -> None:
        result = await _run(
            response=_completed(stdout=json.dumps({"data": {"viewer": {"login": "ann"}}}))
        )

        assert isinstance(result, SuccessResult)
        assert result.value == {"viewer": {"login": "ann"}}

    @pytest.mark.asyncio
    async def test_missing_data_is_an_empty_object(self) -> None:
        result = await _run(response=_completed(stdout="{}"))

        assert result.value == {}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("response", "message"),
        [
            (_completed(returncode=1, stderr="HTTP 502"), "HTTP 502"),
            (_completed(returncode=1), "GitHub GraphQL call failed"),
            (_completed(stdout="nope"), "Invalid JSON"),
            (_completed(stdout="[]"), "not an object"),
            (
                _completed(stdout=json.dumps({"errors": [{"message": "bad field"}]})),
                "GitHub GraphQL error: bad field",
            ),
            (
                _completed(stdout=json.dumps({"errors": {"message": "rate limited"}})),
                "GitHub GraphQL error: rate limited",
            ),
            (
                _completed(stdout=json.dumps({"errors": ["plain text"]})),
                "GitHub GraphQL error: plain text",
            ),
        ],
    )
    async def test_failures_are_errors(self, response: Any, message: str) -> None:
        result = await _run(response=response)

        assert isinstance(result, ErrorResult)
        assert message in result.error


async def _pull_request(*, response: Any) -> Any:
    with patch.object(_gateway, "_gh_api_raw", new_callable=AsyncMock, return_value=response):
        return await _gateway._graphql_pull_request(
            "query { }", ref=RepositoryRef(owner="o", name="r"), pr_number=7
        )


class TestGraphqlPullRequest:
    @pytest.mark.asyncio
    async def test_returns_the_pull_request_node(self) -> None:
        node = {"headRefOid": "abc"}
        response = _completed(stdout=json.dumps({"data": {"repository": {"pullRequest": node}}}))

        result = await _pull_request(response=response)

        assert isinstance(result, SuccessResult)
        assert result.value == node

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "repository",
        [{"pullRequest": None}, {}, None, {"pullRequest": []}],
        ids=["null-pull-request", "missing-pull-request", "null-repository", "list-node"],
    )
    async def test_an_unknown_pr_is_an_error(self, repository: Any) -> None:
        response = _completed(stdout=json.dumps({"data": {"repository": repository}}))

        result = await _pull_request(response=response)

        assert isinstance(result, ErrorResult)
        assert result.error == "PR #7 not found in o/r"

    @pytest.mark.asyncio
    async def test_a_graphql_error_passes_through(self) -> None:
        result = await _pull_request(response=_completed(returncode=1, stderr="HTTP 502"))

        assert isinstance(result, ErrorResult)
        assert "HTTP 502" in result.error
