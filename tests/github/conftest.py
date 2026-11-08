from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from dev10x.domain.common.repository_ref import RepositoryRef
from dev10x.domain.common.result import ok

from dev10x.core.github import _gateway


@pytest.fixture
def mock_resolve_repo() -> Iterator[AsyncMock]:
    with patch.object(
        _gateway,
        "_resolve_repo",
        new_callable=AsyncMock,
        return_value=ok(RepositoryRef(owner="owner", name="repo")),
    ) as mock:
        yield mock


@pytest.fixture
def mock_graphql() -> Iterator[AsyncMock]:
    with patch.object(_gateway, "_gh_api_raw", new_callable=AsyncMock) as mock:
        yield mock
