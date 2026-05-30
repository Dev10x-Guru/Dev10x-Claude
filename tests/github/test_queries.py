"""Tests for PRStatusQuery — query generation, parsing, and batch_find_prs."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from dev10x.domain.common.repository_ref import RepositoryRef
from dev10x.domain.common.result import ErrorResult, SuccessResult
from dev10x.github.queries import PRStatus, PRStatusQuery, batch_find_prs


@pytest.fixture
def repo() -> RepositoryRef:
    return RepositoryRef.parse("org/repo")


@pytest.fixture
def query(repo: RepositoryRef) -> PRStatusQuery:
    return PRStatusQuery(repo=repo)


class TestPRStatusQueryForSingle:
    def test_includes_owner_and_name(self, query: PRStatusQuery) -> None:
        body = query.for_pr(number=42)
        assert 'owner: "org"' in body
        assert 'name: "repo"' in body
        assert "pullRequest(number: 42)" in body

    def test_requests_status_fields(self, query: PRStatusQuery) -> None:
        body = query.for_pr(number=1)
        for field in (
            "number",
            "title",
            "state",
            "isDraft",
            "mergedAt",
            "headRefName",
            "baseRefName",
            "mergeable",
            "reviewDecision",
            "url",
        ):
            assert field in body


class TestPRStatusQueryForBatch:
    def test_uses_aliases_for_each_pr(self, query: PRStatusQuery) -> None:
        body = query.for_prs(numbers=[1, 2, 3])
        assert "pr1: pullRequest(number: 1)" in body
        assert "pr2: pullRequest(number: 2)" in body
        assert "pr3: pullRequest(number: 3)" in body

    def test_deduplicates_numbers(self, query: PRStatusQuery) -> None:
        body = query.for_prs(numbers=[5, 5, 5])
        assert body.count("pr5:") == 1

    def test_orders_numbers_ascending_for_stable_output(self, query: PRStatusQuery) -> None:
        body = query.for_prs(numbers=[3, 1, 2])
        assert body.index("pr1:") < body.index("pr2:") < body.index("pr3:")

    def test_empty_numbers_raises(self, query: PRStatusQuery) -> None:
        with pytest.raises(ValueError, match="at least one PR number"):
            query.for_prs(numbers=[])


class TestPRStatusFromNode:
    def test_parses_full_node(self) -> None:
        node = {
            "number": 42,
            "title": "Fix bug",
            "state": "OPEN",
            "isDraft": True,
            "mergedAt": None,
            "headRefName": "feature/x",
            "baseRefName": "develop",
            "mergeable": "MERGEABLE",
            "reviewDecision": "APPROVED",
            "url": "https://github.com/org/repo/pull/42",
        }
        status = PRStatus.from_node(node=node)
        assert status.number == 42
        assert status.title == "Fix bug"
        assert status.state == "OPEN"
        assert status.is_draft is True
        assert status.merged_at is None
        assert status.head_ref_name == "feature/x"
        assert status.review_decision == "APPROVED"

    def test_tolerates_missing_optional_fields(self) -> None:
        status = PRStatus.from_node(node={"number": "7"})
        assert status.number == 7
        assert status.title == ""
        assert status.is_draft is False
        assert status.merged_at is None


class TestParseSingle:
    def test_returns_status_when_node_present(self) -> None:
        data = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "number": 42,
                        "title": "Fix bug",
                        "state": "OPEN",
                        "isDraft": False,
                        "mergedAt": None,
                        "headRefName": "feature/x",
                        "baseRefName": "develop",
                        "mergeable": "MERGEABLE",
                        "reviewDecision": None,
                        "url": "https://github.com/org/repo/pull/42",
                    }
                }
            }
        }
        status = PRStatusQuery.parse_single(data=data)
        assert status is not None
        assert status.number == 42
        assert status.title == "Fix bug"

    def test_returns_none_when_pull_request_node_absent(self) -> None:
        data: dict = {"data": {"repository": {}}}
        assert PRStatusQuery.parse_single(data=data) is None

    def test_returns_none_when_data_empty(self) -> None:
        assert PRStatusQuery.parse_single(data={}) is None


class TestParseBatch:
    def test_extracts_each_requested_pr(self) -> None:
        data = {
            "data": {
                "repository": {
                    "pr1": {"number": 1, "title": "First", "state": "MERGED"},
                    "pr2": {"number": 2, "title": "Second", "state": "OPEN"},
                }
            }
        }
        parsed = PRStatusQuery.parse_batch(data=data, numbers=[1, 2])
        assert set(parsed.keys()) == {1, 2}
        assert parsed[1].title == "First"
        assert parsed[2].state == "OPEN"

    def test_skips_null_pr_nodes(self) -> None:
        data = {
            "data": {
                "repository": {
                    "pr1": {"number": 1, "title": "First", "state": "MERGED"},
                    "pr99": None,
                }
            }
        }
        parsed = PRStatusQuery.parse_batch(data=data, numbers=[1, 99])
        assert set(parsed.keys()) == {1}

    def test_empty_data_returns_empty_dict(self) -> None:
        assert PRStatusQuery.parse_batch(data={}, numbers=[1, 2]) == {}


class TestBatchFindPrs:
    @pytest.mark.asyncio
    async def test_empty_numbers_short_circuits(self) -> None:
        result = await batch_find_prs(numbers=[], repo="org/repo")
        assert isinstance(result, SuccessResult)
        assert result.value == {}

    @pytest.mark.asyncio
    async def test_returns_parsed_status_on_success(self) -> None:
        payload = {
            "data": {
                "repository": {
                    "pr1": {
                        "number": 1,
                        "title": "Hello",
                        "state": "OPEN",
                        "isDraft": False,
                        "mergedAt": None,
                        "headRefName": "h",
                        "baseRefName": "develop",
                        "mergeable": "MERGEABLE",
                        "reviewDecision": None,
                        "url": "u",
                    }
                }
            }
        }

        class _Proc:
            returncode = 0
            stdout = json.dumps(payload)
            stderr = ""

        async def _fake_gh_api(*args, **kwargs):
            return _Proc()

        with patch("dev10x.github._gh_api_raw", side_effect=_fake_gh_api):
            result = await batch_find_prs(numbers=[1], repo="org/repo")

        assert isinstance(result, SuccessResult)
        assert result.value[1].title == "Hello"

    @pytest.mark.asyncio
    async def test_returns_error_when_gh_fails(self) -> None:
        class _Proc:
            returncode = 1
            stdout = ""
            stderr = "gh: auth required\n"

        async def _fake_gh_api(*args, **kwargs):
            return _Proc()

        with patch("dev10x.github._gh_api_raw", side_effect=_fake_gh_api):
            result = await batch_find_prs(numbers=[1, 2], repo="org/repo")

        assert isinstance(result, ErrorResult)
        assert "gh: auth required" in result.error

    @pytest.mark.asyncio
    async def test_returns_error_on_invalid_json(self) -> None:
        class _Proc:
            returncode = 0
            stdout = "not json"
            stderr = ""

        async def _fake_gh_api(*args, **kwargs):
            return _Proc()

        with patch("dev10x.github._gh_api_raw", side_effect=_fake_gh_api):
            result = await batch_find_prs(numbers=[1], repo="org/repo")

        assert isinstance(result, ErrorResult)
        assert "Invalid JSON" in result.error
