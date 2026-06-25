"""Tests for the @github_tool decorator (GH-585)."""

from __future__ import annotations

import inspect
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


class TestGithubToolOutputSchema:
    """Regression guard for the 0.80.0 MCP output-schema break (GH-712, GH-713).

    ``functools.wraps`` leaked the inner ``-> Result[dict]`` annotation onto
    the wrapper, so FastMCP derived a ``SuccessResult | ErrorResult`` output
    schema and rejected the flattened ``to_wire()`` dict that the handler
    actually returns — every github tool failed output validation despite the
    underlying GitHub call succeeding. The fix pins the public return
    annotation to ``dict`` (no output schema derived), matching the
    directly-``@server.tool()`` handlers.
    """

    AFFECTED_TOOLS = (
        "issue_get",
        "pr_comments",
        "pr_comment_reply",
        "detect_base_branch",
        "verify_pr_state",
    )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_name", AFFECTED_TOOLS)
    async def test_no_output_schema_derived(self, tool_name: str) -> None:
        tools = await cli_server.server.list_tools()
        by_name = {tool.name: tool for tool in tools}

        assert by_name[tool_name].outputSchema is None

    @pytest.mark.parametrize("tool_name", AFFECTED_TOOLS)
    def test_public_return_annotation_is_dict(self, tool_name: str) -> None:
        fn = getattr(github_tools, tool_name)

        assert inspect.signature(fn).return_annotation is dict
