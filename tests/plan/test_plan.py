from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

plan_mod = pytest.importorskip("dev10x.plan", reason="dev10x not installed")

TASK_PLAN_SYNC = "dev10x.hooks.task_plan_sync"


class TestSetContext:
    @pytest.mark.asyncio
    @patch(f"{TASK_PLAN_SYNC}.get_toplevel", return_value=None)
    async def test_returns_error_when_not_in_git_repo(
        self,
        mock_toplevel: MagicMock,
    ) -> None:
        result = await plan_mod.set_context(args=["key=value"])
        assert result == {"error": "Not in a git repository"}

    @pytest.mark.asyncio
    @patch(f"{TASK_PLAN_SYNC}.get_toplevel", return_value="/tmp/repo")
    @patch(f"{TASK_PLAN_SYNC}.get_plan_path")
    @patch(f"{TASK_PLAN_SYNC}.Plan")
    async def test_returns_error_for_invalid_arg(
        self,
        mock_plan_cls: MagicMock,
        mock_plan_path: MagicMock,
        mock_toplevel: MagicMock,
    ) -> None:
        mock_plan = MagicMock()
        mock_plan_cls.load.return_value = mock_plan
        result = await plan_mod.set_context(args=["no-equals-sign"])
        assert "error" in result

    @pytest.mark.asyncio
    @patch(f"{TASK_PLAN_SYNC}.get_toplevel", return_value="/tmp/repo")
    @patch(f"{TASK_PLAN_SYNC}.get_plan_path")
    @patch(f"{TASK_PLAN_SYNC}.Plan")
    async def test_sets_context_successfully(
        self,
        mock_plan_cls: MagicMock,
        mock_plan_path: MagicMock,
        mock_toplevel: MagicMock,
    ) -> None:
        mock_plan = MagicMock()
        mock_plan.metadata = {"context": {"key": "value"}}
        mock_plan_cls.load.return_value = mock_plan
        result = await plan_mod.set_context(args=["key=value"])
        assert result["success"] is True
        assert "key" in result["updated_keys"]


class TestJsonSummary:
    @pytest.mark.asyncio
    @patch(f"{TASK_PLAN_SYNC}.get_toplevel", return_value=None)
    async def test_returns_empty_when_not_in_git_repo(
        self,
        mock_toplevel: MagicMock,
    ) -> None:
        result = await plan_mod.json_summary()
        assert result == {}

    @pytest.mark.asyncio
    @patch(f"{TASK_PLAN_SYNC}.get_toplevel", return_value="/tmp/repo")
    @patch(f"{TASK_PLAN_SYNC}.get_plan_path")
    @patch(f"{TASK_PLAN_SYNC}.Plan")
    async def test_returns_empty_when_no_metadata(
        self,
        mock_plan_cls: MagicMock,
        mock_plan_path: MagicMock,
        mock_toplevel: MagicMock,
    ) -> None:
        mock_plan = MagicMock()
        mock_plan.metadata = {}
        mock_plan_cls.load.return_value = mock_plan
        result = await plan_mod.json_summary()
        assert result == {}

    @pytest.mark.asyncio
    @patch(f"{TASK_PLAN_SYNC}.get_toplevel", return_value="/tmp/repo")
    @patch(f"{TASK_PLAN_SYNC}.get_plan_path")
    @patch(f"{TASK_PLAN_SYNC}.Plan")
    async def test_returns_plan_dict(
        self,
        mock_plan_cls: MagicMock,
        mock_plan_path: MagicMock,
        mock_toplevel: MagicMock,
    ) -> None:
        mock_plan = MagicMock()
        mock_plan.metadata = {"branch": "feature"}
        mock_plan._to_dict.return_value = {"metadata": {"branch": "feature"}}
        mock_plan_cls.load.return_value = mock_plan
        result = await plan_mod.json_summary()
        assert result == {"metadata": {"branch": "feature"}}


class TestArchive:
    @pytest.mark.asyncio
    @patch(f"{TASK_PLAN_SYNC}.get_toplevel", return_value=None)
    async def test_returns_error_when_not_in_git_repo(
        self,
        mock_toplevel: MagicMock,
    ) -> None:
        result = await plan_mod.archive()
        assert result == {"error": "Not in a git repository"}

    @pytest.mark.asyncio
    @patch(f"{TASK_PLAN_SYNC}.get_toplevel", return_value="/tmp/repo")
    @patch(f"{TASK_PLAN_SYNC}.get_plan_path")
    async def test_returns_success_when_no_plan_file(
        self,
        mock_plan_path: MagicMock,
        mock_toplevel: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_plan_path.return_value = tmp_path / "nonexistent.yaml"
        result = await plan_mod.archive()
        assert result["success"] is True
        assert "No plan file" in result["message"]
