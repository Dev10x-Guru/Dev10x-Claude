from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock, patch

import pytest

util_mod = pytest.importorskip("dev10x.utilities", reason="dev10x not installed")
from dev10x.domain.common.result import ErrorResult, SuccessResult  # noqa: E402


class TestMktmp:
    @pytest.mark.asyncio
    @patch("dev10x.utilities.async_run_script", new_callable=AsyncMock)
    async def test_returns_path_on_success(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="/tmp/Dev10x/git/msg.abc.txt",
            stderr="",
        )
        result = await util_mod.mktmp(namespace="git", prefix="msg", ext=".txt")
        assert isinstance(result, SuccessResult)
        assert result.value == {"path": "/tmp/Dev10x/git/msg.abc.txt"}

    @pytest.mark.asyncio
    @patch("dev10x.utilities.async_run_script", new_callable=AsyncMock)
    async def test_returns_structured_error_on_failure(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="Permission denied",
        )
        result = await util_mod.mktmp(namespace="git", prefix="msg")
        assert isinstance(result, ErrorResult)
        assert result.error == "Permission denied"
        assert result.to_dict() == {"error": "Permission denied"}
