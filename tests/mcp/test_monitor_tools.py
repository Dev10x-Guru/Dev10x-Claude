"""Tests for the monitor MCP tool handlers (GH-585)."""

from __future__ import annotations

import subprocess
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
            "max_polls": 40,
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
    @patch("dev10x.monitor.async_run", new_callable=AsyncMock)
    async def test_subprocess_cap_is_1320s_distinct_from_poll_budget(
        self,
        mock_run: AsyncMock,
    ) -> None:
        """GH-1104: 1320s is the SUBPROCESS cap, not the poll budget.

        `poll_until_terminal`'s in-loop budget is 1230s (it skips the sleep
        after the final poll). This wrapper adds a 60s grace on top of the
        ×40 upper bound, which is where 1320 comes from. Pinning it here
        keeps the two ceilings from being conflated again.
        """
        import dev10x.monitor as monitor

        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="{}", stderr=""
        )

        await monitor.ci_check_status(pr_number=1, repo="o/r", wait=True)

        assert mock_run.call_args.kwargs["timeout"] == 1320.0

    @pytest.mark.asyncio
    async def test_use_cwd_activates_when_cwd_passed(self, tmp_path) -> None:
        with patch("dev10x.subprocess_utils.use_cwd") as mock_use_cwd:
            try:
                await cli_server.ci_check_status(pr_number=1, repo="o/r", cwd=str(tmp_path))
            except Exception:
                pass

        mock_use_cwd.assert_called_once_with(str(tmp_path))
