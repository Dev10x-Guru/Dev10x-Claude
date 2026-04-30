from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock, patch

import pytest

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
        assert result["verdict"] == "green"
        assert result["total"] == 3

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
        assert "error" in result

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
        assert "error" in result

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
