"""Tests for the monitor MCP tool handlers (GH-585)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from dev10x.domain.common.result import err, ok
from dev10x.mcp import server_cli as cli_server


class TestCiCheckStatusMcp:
    @pytest.mark.asyncio
    @patch("dev10x.monitor.ci_check_status", new_callable=AsyncMock)
    async def test_delegates_to_monitor_module(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = ok({"verdict": "green", "mergeable": True})

        result = await cli_server.ci_check_status(pr_number=42, repo="o/r")

        assert result == {"verdict": "green", "mergeable": True}
        assert mock_fn.call_args.kwargs == {
            "pr_number": 42,
            "repo": "o/r",
            "required_only": False,
            "wait": False,
            "poll_interval": 30,
            "initial_wait": 60,
            "max_polls": 60,
        }

    @pytest.mark.asyncio
    @patch("dev10x.monitor.ci_check_status", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = err("rate limit")

        result = await cli_server.ci_check_status(pr_number=42, repo="o/r")

        assert "error" in result

    @pytest.mark.asyncio
    async def test_use_cwd_activates_when_cwd_passed(self, tmp_path) -> None:
        with patch("dev10x.subprocess_utils.use_cwd") as mock_use_cwd:
            try:
                await cli_server.ci_check_status(pr_number=1, repo="o/r", cwd=str(tmp_path))
            except Exception:
                pass

        mock_use_cwd.assert_called_once_with(str(tmp_path))
