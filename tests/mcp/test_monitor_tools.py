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
        # wait_out_pending and wait_for MUST appear here: the boundary
        # previously declared wait_out_pending and dropped it before the
        # domain call, so passing False did nothing. This assertion had
        # pinned that omission, which is why it went unnoticed (GH-1138).
        assert mock_fn.call_args.kwargs == {
            "pr_number": 42,
            "repo": "o/r",
            "required_only": False,
            "wait": False,
            "poll_interval": 30,
            "initial_wait": 60,
            "max_polls": 40,
            "wait_out_pending": True,
            "wait_for": None,
        }

    @pytest.mark.asyncio
    @patch("dev10x.monitor.ci_check_status", new_callable=AsyncMock)
    async def test_forwards_wait_for_and_wait_out_pending(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = ok({"verdict": "failing"})

        await cli_server.ci_check_status(
            pr_number=42,
            repo="o/r",
            wait=True,
            wait_out_pending=False,
            wait_for=["claude-review"],
        )

        assert mock_fn.call_args.kwargs["wait_out_pending"] is False
        assert mock_fn.call_args.kwargs["wait_for"] == ["claude-review"]

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
    async def test_subprocess_cap_is_distinct_from_the_poll_budget(
        self,
        mock_run: AsyncMock,
    ) -> None:
        """GH-1104: the cap is the SUBPROCESS ceiling, not the poll budget.

        Two numbers, and conflating them is the mistake this pins against.
        The loop must finish strictly inside the cap, or it gets killed
        mid-poll and the caller reads an exit code where it expected a
        verdict.

        The figures moved under GH-1288: the cap was 1320s, summed inline
        from `max_polls` with nothing bounding it, which put it above the
        transport ceiling and above both deaths the issue reports at
        ~1137s. The ×40 request is now served as ×32 — 990s of polling
        (the loop skips the sleep after the final poll) under a 1080s cap.
        """
        import dev10x.monitor as monitor

        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="{}", stderr=""
        )

        await monitor.ci_check_status(pr_number=1, repo="o/r", wait=True)

        args_list = mock_run.call_args.kwargs["args"]
        granted = int(args_list[args_list.index("--max-polls") + 1])
        poll_budget = 60 + 30 * (granted - 1)

        assert mock_run.call_args.kwargs["timeout"] == 1080.0
        assert poll_budget == 990
        assert poll_budget < mock_run.call_args.kwargs["timeout"]

    @pytest.mark.asyncio
    async def test_use_cwd_activates_when_cwd_passed(self, tmp_path) -> None:
        with patch("dev10x.subprocess_utils.use_cwd") as mock_use_cwd:
            try:
                await cli_server.ci_check_status(pr_number=1, repo="o/r", cwd=str(tmp_path))
            except Exception:
                pass

        mock_use_cwd.assert_called_once_with(str(tmp_path))
