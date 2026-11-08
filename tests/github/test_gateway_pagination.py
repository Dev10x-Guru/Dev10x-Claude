"""_gh_api_paginated: one REST paging policy for every listing (GH-1852)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest
from dev10x.domain.common.result import ErrorResult, SuccessResult

from dev10x.core.github import _gateway
from tests.fakers.process import completed as _completed

BASE = "repos/o/r/things"


def _page(*, count: int, key: str | None = None) -> Any:
    items = [{"id": index} for index in range(count)]
    return _completed(stdout=json.dumps({key: items} if key else items))


class Pages:
    def __init__(self, *pages: Any) -> None:
        self.pages = list(pages)
        self.calls: list[str] = []

    async def __call__(self, endpoint: str, **_: Any) -> Any:
        self.calls.append(endpoint)
        return self.pages[len(self.calls) - 1]


async def _list(*, pages: Pages, endpoint: str = BASE, **kwargs: Any) -> Any:
    with patch.object(_gateway, "_gh_api_raw", new=pages):
        return await _gateway._gh_api_paginated(endpoint, label="things", **kwargs)


class TestGhApiPaginated:
    @pytest.mark.asyncio
    async def test_a_short_first_page_ends_the_listing(self) -> None:
        pages = Pages(_page(count=3))

        result = await _list(pages=pages)

        assert isinstance(result, SuccessResult)
        assert (len(result.value.items), result.value.truncated) == (3, False)
        assert pages.calls == [f"{BASE}?per_page=100"]

    @pytest.mark.asyncio
    async def test_follows_full_pages_and_keeps_an_existing_query(self) -> None:
        pages = Pages(_page(count=100, key="runs"), _page(count=1, key="runs"))

        result = await _list(pages=pages, endpoint=f"{BASE}?sha=abc", key="runs")

        assert len(result.value.items) == 101
        assert pages.calls == [
            f"{BASE}?sha=abc&per_page=100",
            f"{BASE}?sha=abc&per_page=100&page=2",
        ]

    @pytest.mark.asyncio
    async def test_reports_truncation_at_the_page_ceiling(self) -> None:
        pages = Pages(*[_page(count=100)] * 2)

        result = await _list(pages=pages, max_pages=2)

        assert (len(result.value.items), result.value.truncated) == (200, True)

    @pytest.mark.asyncio
    async def test_drops_non_object_items(self) -> None:
        pages = Pages(_completed(stdout=json.dumps([{"id": 1}, "noise", 3])))

        result = await _list(pages=pages)

        assert result.value.items == ({"id": 1},)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("page", "message"),
        [
            (_completed(returncode=1, stderr="HTTP 403"), "HTTP 403"),
            (_completed(returncode=1), "could not list things"),
            (_completed(stdout="nope"), "could not parse things as JSON"),
            (_completed(stdout="{}"), "unexpected things shape"),
        ],
    )
    async def test_failures_are_errors(self, page: Any, message: str) -> None:
        result = await _list(pages=Pages(page))

        assert isinstance(result, ErrorResult)
        assert message in result.error

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", ["{}", "[]"])
    async def test_a_keyed_listing_needs_its_key(self, payload: str) -> None:
        result = await _list(pages=Pages(_completed(stdout=payload)), key="runs")

        assert isinstance(result, ErrorResult)
        assert "unexpected things shape" in result.error
