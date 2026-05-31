from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

plan_mod = pytest.importorskip("dev10x.plan", reason="dev10x not installed")
from dev10x.domain.common.result import ErrorResult, SuccessResult  # noqa: E402

SERVICE = "dev10x.plan.service"


class TestSetContext:
    @pytest.mark.asyncio
    @patch(f"{SERVICE}.get_toplevel", return_value=None)
    async def test_returns_error_when_not_in_git_repo(
        self,
        mock_toplevel: MagicMock,
    ) -> None:
        result = await plan_mod.set_context(args=["key=value"])
        assert isinstance(result, ErrorResult)
        assert result.error == "Not in a git repository"
        assert result.to_dict() == {"error": "Not in a git repository"}

    @pytest.mark.asyncio
    @patch(f"{SERVICE}.get_toplevel", return_value="/tmp/repo")
    @patch(f"{SERVICE}.get_plan_path")
    @patch(f"{SERVICE}.Plan")
    async def test_returns_error_for_invalid_arg(
        self,
        mock_plan_cls: MagicMock,
        mock_plan_path: MagicMock,
        mock_toplevel: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_plan_path.return_value = tmp_path / "plan.yaml"
        mock_plan = MagicMock()
        mock_plan_cls.load.return_value = mock_plan
        result = await plan_mod.set_context(args=["no-equals-sign"])
        assert isinstance(result, ErrorResult)

    @pytest.mark.asyncio
    @patch(f"{SERVICE}.get_toplevel", return_value="/tmp/repo")
    @patch(f"{SERVICE}.get_plan_path")
    @patch(f"{SERVICE}.Plan")
    async def test_sets_context_successfully(
        self,
        mock_plan_cls: MagicMock,
        mock_plan_path: MagicMock,
        mock_toplevel: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_plan_path.return_value = tmp_path / "plan.yaml"
        mock_plan = MagicMock()
        mock_plan.context_keys.return_value = ["key"]
        mock_plan_cls.load.return_value = mock_plan
        result = await plan_mod.set_context(args=["key=value"])
        assert isinstance(result, SuccessResult)
        assert result.value["success"] is True
        assert "key" in result.value["updated_keys"]


class TestJsonSummary:
    @pytest.mark.asyncio
    @patch(f"{SERVICE}.get_toplevel", return_value=None)
    async def test_returns_error_when_not_in_git_repo(
        self,
        mock_toplevel: MagicMock,
    ) -> None:
        result = await plan_mod.json_summary()
        assert isinstance(result, ErrorResult)
        assert result.error == "Not in a git repository"

    @pytest.mark.asyncio
    @patch(f"{SERVICE}.get_toplevel", return_value="/tmp/repo")
    @patch(f"{SERVICE}.get_plan_path")
    @patch(f"{SERVICE}.Plan")
    async def test_returns_empty_when_no_metadata(
        self,
        mock_plan_cls: MagicMock,
        mock_plan_path: MagicMock,
        mock_toplevel: MagicMock,
    ) -> None:
        mock_plan = MagicMock()
        mock_plan.is_new = True
        mock_plan_cls.load.return_value = mock_plan
        result = await plan_mod.json_summary()
        assert isinstance(result, SuccessResult)
        assert result.value == {}

    @pytest.mark.asyncio
    @patch(f"{SERVICE}.get_toplevel", return_value="/tmp/repo")
    @patch(f"{SERVICE}.get_plan_path")
    @patch(f"{SERVICE}.Plan")
    async def test_returns_plan_dict(
        self,
        mock_plan_cls: MagicMock,
        mock_plan_path: MagicMock,
        mock_toplevel: MagicMock,
    ) -> None:
        mock_plan = MagicMock()
        mock_plan.is_new = False
        mock_plan.to_dict.return_value = {"metadata": {"branch": "feature"}}
        mock_plan_cls.load.return_value = mock_plan
        result = await plan_mod.json_summary()
        assert isinstance(result, SuccessResult)
        assert result.value == {"metadata": {"branch": "feature"}}


class TestArchive:
    @pytest.mark.asyncio
    @patch(f"{SERVICE}.get_toplevel", return_value=None)
    async def test_returns_error_when_not_in_git_repo(
        self,
        mock_toplevel: MagicMock,
    ) -> None:
        result = await plan_mod.archive()
        assert isinstance(result, ErrorResult)
        assert result.error == "Not in a git repository"

    @pytest.mark.asyncio
    @patch(f"{SERVICE}.get_toplevel", return_value="/tmp/repo")
    @patch(f"{SERVICE}.get_plan_path")
    async def test_returns_success_when_no_plan_file(
        self,
        mock_plan_path: MagicMock,
        mock_toplevel: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_plan_path.return_value = tmp_path / "nonexistent.yaml"
        result = await plan_mod.archive()
        assert isinstance(result, SuccessResult)
        assert result.value["success"] is True
        assert "No plan file" in result.value["message"]
