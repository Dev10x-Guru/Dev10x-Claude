from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock, patch

import pytest

rel_mod = pytest.importorskip("dev10x.release", reason="dev10x not installed")


class TestCollectPrs:
    @pytest.mark.asyncio
    @patch("dev10x.release.async_run", new_callable=AsyncMock)
    async def test_returns_output_on_success(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="## Release Notes\n- PR #1",
            stderr="",
        )
        result = await rel_mod.collect_prs(repo_path="/tmp/repo")
        assert result["success"] is True

    @pytest.mark.asyncio
    @patch("dev10x.release.async_run", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="Not a git repo",
        )
        result = await rel_mod.collect_prs(repo_path="/tmp/repo")
        assert "error" in result

    @pytest.mark.asyncio
    @patch("dev10x.release.async_run", new_callable=AsyncMock)
    async def test_passes_optional_args(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="OK",
            stderr="",
        )
        await rel_mod.collect_prs(
            repo_path="/tmp/repo",
            from_tag="v1.0",
            to_tag="v2.0",
            ticket_pattern="GH-\\d+",
        )
        call_args = mock_run.call_args
        args_list = call_args.kwargs["args"]
        assert "--from" in args_list
        assert "v1.0" in args_list
        assert "--to" in args_list
        assert "--ticket-pattern" in args_list
