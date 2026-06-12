"""Tests for the @github_tool decorator (GH-585)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from dev10x.domain.common.result import err, ok
from dev10x.mcp import github_tools
from dev10x.mcp import server_cli as cli_server


class TestGithubToolSchema:
    @pytest.mark.asyncio
    async def test_decorated_tool_registered_with_input_schema(self) -> None:
        tools = await cli_server.server.list_tools()
        by_name = {tool.name: tool for tool in tools}

        assert "issue_get" in by_name
        props = by_name["issue_get"].inputSchema["properties"]
        assert "number" in props
        assert "repo" in props


class TestGithubToolDelegation:
    @pytest.mark.asyncio
    @patch("dev10x.github.issue_get")
    async def test_returns_inner_result_to_dict(self, mock_fn) -> None:
        async def _fake(**kwargs):
            return ok({"title": "t", "state": "open"})

        mock_fn.side_effect = _fake

        result = await github_tools.issue_get(number=1, repo="o/r")

        assert result == {"title": "t", "state": "open"}

    @pytest.mark.asyncio
    @patch("dev10x.github.issue_get")
    async def test_error_result_passes_through(self, mock_fn) -> None:
        async def _fake(**kwargs):
            return err("Not Found")

        mock_fn.side_effect = _fake

        result = await github_tools.issue_get(number=1, repo="o/r")

        assert result == {"error": "Not Found"}

    @pytest.mark.asyncio
    @patch("dev10x.github.issue_get")
    async def test_enters_use_cwd_with_passed_cwd(self, mock_fn, tmp_path) -> None:
        async def _fake(**kwargs):
            return ok({})

        mock_fn.side_effect = _fake

        with patch("dev10x.subprocess_utils.use_cwd") as mock_use_cwd:
            await github_tools.issue_get(number=1, repo="o/r", cwd=str(tmp_path))

        mock_use_cwd.assert_called_once_with(str(tmp_path))

    @pytest.mark.asyncio
    @patch("dev10x.github.issue_get")
    async def test_use_cwd_receives_none_when_cwd_omitted(self, mock_fn) -> None:
        async def _fake(**kwargs):
            return ok({})

        mock_fn.side_effect = _fake

        with patch("dev10x.subprocess_utils.use_cwd") as mock_use_cwd:
            await github_tools.issue_get(number=1, repo="o/r")

        mock_use_cwd.assert_called_once_with(None)
