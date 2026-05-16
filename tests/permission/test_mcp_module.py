"""Tests for dev10x.permission MCP module (GH-108 Result[T] migration).

Covers the structured-error contract for update_paths — both the
sub-command branch and the subprocess branch — so the boundary
handler in server_cli.py can rely on .to_dict() to render the
envelope at the MCP edge.
"""

from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock, patch

import pytest

perm_mod = pytest.importorskip("dev10x.permission", reason="dev10x not installed")
from dev10x.domain.common.result import ErrorResult, SuccessResult  # noqa: E402


class TestUpdatePathsSubprocess:
    @pytest.mark.asyncio
    @patch("dev10x.permission.async_run", new_callable=AsyncMock)
    async def test_returns_success_on_zero_exit(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="paths updated",
            stderr="",
        )
        result = await perm_mod.update_paths()
        assert isinstance(result, SuccessResult)
        assert result.value["success"] is True
        assert result.value["output"] == "paths updated"

    @pytest.mark.asyncio
    @patch("dev10x.permission.async_run", new_callable=AsyncMock)
    async def test_returns_structured_error_on_failure(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="config not found",
        )
        result = await perm_mod.update_paths()
        assert isinstance(result, ErrorResult)
        assert result.error == "config not found"
        assert result.to_dict() == {"error": "config not found"}


class TestUpdatePathsSubCommand:
    @pytest.mark.asyncio
    async def test_returns_error_when_no_settings_files(self) -> None:
        with (
            patch("dev10x.skills.permission.update_paths.find_config"),
            patch(
                "dev10x.skills.permission.update_paths.load_config",
                return_value={"roots": [], "include_user_settings": False},
            ),
            patch(
                "dev10x.skills.permission.update_paths.find_settings_files",
                return_value=[],
            ),
        ):
            result = await perm_mod.update_paths(ensure_base=True)
        assert isinstance(result, ErrorResult)
        assert "No settings files" in result.error
