from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock, patch

import pytest

from dev10x.domain.common.result import ErrorResult, SuccessResult

monitor_mod = pytest.importorskip("dev10x.monitor", reason="dev10x not installed")


class TestCiCheckStatus:
    @pytest.mark.asyncio
    @patch("dev10x.monitor.async_run", new_callable=AsyncMock)
    async def test_returns_verdict_on_success(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"verdict": "green", "total": 3, "pass": 3, "fail": 0, "pending": 0}',
            stderr="",
        )
        result = await monitor_mod.ci_check_status(pr_number=42, repo="owner/repo")
        assert isinstance(result, SuccessResult)
        assert result.value["verdict"] == "green"
        assert result.value["total"] == 3

    @pytest.mark.asyncio
    @patch("dev10x.monitor.async_run", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="Script error",
        )
        result = await monitor_mod.ci_check_status(pr_number=42, repo="owner/repo")
        assert isinstance(result, ErrorResult)
        assert result.error == "Script error"
        assert result.to_dict() == {"error": "Script error"}

    @pytest.mark.asyncio
    @patch("dev10x.monitor.async_run", new_callable=AsyncMock)
    async def test_returns_error_on_invalid_json(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="not json",
            stderr="",
        )
        result = await monitor_mod.ci_check_status(pr_number=42, repo="owner/repo")
        assert isinstance(result, ErrorResult)
        assert "Invalid JSON output" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.monitor.async_run", new_callable=AsyncMock)
    async def test_passes_wait_flags(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"verdict": "green"}',
            stderr="",
        )
        await monitor_mod.ci_check_status(
            pr_number=42,
            repo="owner/repo",
            wait=True,
            poll_interval=10,
            initial_wait=5,
            max_polls=3,
        )
        call_args = mock_run.call_args
        args_list = call_args.kwargs["args"]
        assert "--wait" in args_list
        assert "--poll-interval" in args_list
        assert "10" in args_list

    @pytest.mark.asyncio
    @patch("dev10x.monitor.async_run", new_callable=AsyncMock)
    async def test_passes_required_only_flag(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"verdict": "green"}',
            stderr="",
        )
        await monitor_mod.ci_check_status(
            pr_number=42,
            repo="owner/repo",
            required_only=True,
        )
        call_args = mock_run.call_args
        args_list = call_args.kwargs["args"]
        assert "--required-only" in args_list

    @pytest.mark.asyncio
    @patch("dev10x.monitor.async_run", new_callable=AsyncMock)
    async def test_wait_out_pending_is_the_default_and_sends_no_flag(
        self,
        mock_run: AsyncMock,
    ) -> None:
        """GH-1065: waiting out pending legs is the default, so the common
        call stays flag-free."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"verdict": "green"}', stderr=""
        )
        await monitor_mod.ci_check_status(pr_number=42, repo="owner/repo", wait=True)
        assert "--no-wait-out-pending" not in mock_run.call_args.kwargs["args"]

    @pytest.mark.asyncio
    @patch("dev10x.monitor.async_run", new_callable=AsyncMock)
    async def test_opting_out_forwards_the_flag(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"verdict": "failing"}', stderr=""
        )
        await monitor_mod.ci_check_status(
            pr_number=42,
            repo="owner/repo",
            wait=True,
            wait_out_pending=False,
        )
        assert "--no-wait-out-pending" in mock_run.call_args.kwargs["args"]

    @pytest.mark.asyncio
    @patch("dev10x.monitor.async_run", new_callable=AsyncMock)
    async def test_opting_out_without_wait_sends_nothing(
        self,
        mock_run: AsyncMock,
    ) -> None:
        """The flag only means something inside the poll loop."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"verdict": "green"}', stderr=""
        )
        await monitor_mod.ci_check_status(
            pr_number=42,
            repo="owner/repo",
            wait_out_pending=False,
        )
        assert "--no-wait-out-pending" not in mock_run.call_args.kwargs["args"]
