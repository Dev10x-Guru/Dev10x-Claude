"""Tests for the release MCP tool handlers (GH-585)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from dev10x.domain.common.result import err, ok
from dev10x.mcp import server_cli as cli_server


class TestCollectPrsMcp:
    @pytest.mark.asyncio
    @patch("dev10x.release.collect_prs", new_callable=AsyncMock)
    async def test_delegates_to_release_module(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = ok({"success": True, "output": "PR list"})

        result = await cli_server.collect_prs(repo_path="/repo")

        assert result == {"success": True, "output": "PR list"}
        assert mock_fn.call_args.kwargs == {
            "repo_path": "/repo",
            "from_tag": None,
            "to_tag": None,
            "ticket_pattern": None,
        }

    @pytest.mark.asyncio
    @patch("dev10x.release.collect_prs", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = err("no tags found")

        result = await cli_server.collect_prs(repo_path="/repo")

        assert "error" in result
