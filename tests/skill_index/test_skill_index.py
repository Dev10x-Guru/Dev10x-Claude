from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock, patch

import pytest

idx_mod = pytest.importorskip("dev10x.skill_index", reason="dev10x not installed")


class TestGenerateAll:
    @pytest.mark.asyncio
    @patch("dev10x.skill_index.async_run_script", new_callable=AsyncMock)
    async def test_returns_output_on_success(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="Generated both files",
            stderr="",
        )
        result = await idx_mod.generate_all()
        assert result["success"] is True

    @pytest.mark.asyncio
    @patch("dev10x.skill_index.async_run_script", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="Script failed",
        )
        result = await idx_mod.generate_all()
        assert "error" in result

    @pytest.mark.asyncio
    @patch("dev10x.skill_index.async_run_script", new_callable=AsyncMock)
    async def test_passes_force_flag(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="OK",
            stderr="",
        )
        await idx_mod.generate_all(force=True)
        call_args = mock_run.call_args
        assert "--force" in call_args.args[1:]
