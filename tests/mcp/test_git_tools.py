"""Tests for git_tools MCP adapter (GH-580).

Covers argument forwarding (especially cwd), ok/err → dict translation,
and error paths for each adapter function in src/dev10x/mcp/git_tools.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from dev10x.domain.common.result import err, ok
from dev10x.mcp import server_cli as cli_server


class TestPushSafe:
    @pytest.mark.asyncio
    @patch("dev10x.git.push_safe", new_callable=AsyncMock)
    async def test_delegates_to_git_module(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = ok({"pushed": True, "branch": "feature"})

        result = await cli_server.push_safe(args=["-u", "origin", "feature"])

        assert result == {"pushed": True, "branch": "feature"}
        assert mock_fn.call_args.kwargs["args"] == ["-u", "origin", "feature"]

    @pytest.mark.asyncio
    @patch("dev10x.git.push_safe", new_callable=AsyncMock)
    async def test_forwards_protected_branches(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = ok({})

        await cli_server.push_safe(
            args=["origin", "main"],
            protected_branches=["main", "develop"],
        )

        assert mock_fn.call_args.kwargs["protected_branches"] == ["main", "develop"]

    @pytest.mark.asyncio
    @patch("dev10x.git.push_safe", new_callable=AsyncMock)
    async def test_returns_error_on_failure(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = err("push blocked: protected branch")

        result = await cli_server.push_safe(args=["origin", "main"])

        assert "error" in result

    @pytest.mark.asyncio
    @patch("dev10x.git.push_safe", new_callable=AsyncMock)
    async def test_forwards_cwd(self, mock_fn: AsyncMock, tmp_path) -> None:
        mock_fn.return_value = ok({})

        with patch("dev10x.subprocess_utils.use_cwd") as mock_use_cwd:
            await cli_server.push_safe(args=["origin", "feature"], cwd=str(tmp_path))

        mock_use_cwd.assert_called_once_with(str(tmp_path))


class TestRebaseGroom:
    @pytest.mark.asyncio
    @patch("dev10x.git.rebase_groom", new_callable=AsyncMock)
    async def test_delegates_to_git_module(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = ok({"commits_rewritten": 3})

        result = await cli_server.rebase_groom(seq_path="/tmp/seq", base_ref="develop")

        assert result == {"commits_rewritten": 3}
        assert mock_fn.call_args.kwargs == {"seq_path": "/tmp/seq", "base_ref": "develop"}

    @pytest.mark.asyncio
    @patch("dev10x.git.rebase_groom", new_callable=AsyncMock)
    async def test_returns_error_on_failure(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = err("rebase conflict at HEAD")

        result = await cli_server.rebase_groom(seq_path="/tmp/seq", base_ref="develop")

        assert "error" in result

    @pytest.mark.asyncio
    @patch("dev10x.git.rebase_groom", new_callable=AsyncMock)
    async def test_forwards_cwd(self, mock_fn: AsyncMock, tmp_path) -> None:
        mock_fn.return_value = ok({"commits_rewritten": 0})

        with patch("dev10x.subprocess_utils.use_cwd") as mock_use_cwd:
            await cli_server.rebase_groom(
                seq_path="/tmp/seq",
                base_ref="develop",
                cwd=str(tmp_path),
            )

        mock_use_cwd.assert_called_once_with(str(tmp_path))


class TestCreateWorktree:
    @pytest.mark.asyncio
    @patch("dev10x.git.create_worktree", new_callable=AsyncMock)
    async def test_delegates_to_git_module(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = ok(
            {"worktree_path": "/work/.worktrees/feature-1", "branch": "feature", "created": True}
        )

        result = await cli_server.create_worktree(branch="feature")

        assert result["created"] is True
        assert mock_fn.call_args.kwargs["branch"] == "feature"

    @pytest.mark.asyncio
    @patch("dev10x.git.create_worktree", new_callable=AsyncMock)
    async def test_forwards_base_and_path(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = ok({"worktree_path": "/tmp/wt", "branch": "feat", "created": True})

        await cli_server.create_worktree(branch="feat", base="main", path="/tmp/wt")

        assert mock_fn.call_args.kwargs["base"] == "main"
        assert mock_fn.call_args.kwargs["path"] == "/tmp/wt"

    @pytest.mark.asyncio
    @patch("dev10x.git.create_worktree", new_callable=AsyncMock)
    async def test_returns_error_on_failure(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = err("branch already checked out")

        result = await cli_server.create_worktree(branch="feature")

        assert "error" in result

    @pytest.mark.asyncio
    @patch("dev10x.git.create_worktree", new_callable=AsyncMock)
    async def test_forwards_cwd(self, mock_fn: AsyncMock, tmp_path) -> None:
        mock_fn.return_value = ok({"worktree_path": "/tmp/wt", "branch": "feat", "created": True})

        with patch("dev10x.subprocess_utils.use_cwd") as mock_use_cwd:
            await cli_server.create_worktree(branch="feat", cwd=str(tmp_path))

        mock_use_cwd.assert_called_once_with(str(tmp_path))


class TestMassRewrite:
    @pytest.mark.asyncio
    @patch("dev10x.git.mass_rewrite", new_callable=AsyncMock)
    async def test_delegates_to_git_module(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = ok({"success": True, "output": "3 commits rewritten"})

        result = await cli_server.mass_rewrite(config_path="/tmp/rewrites.json")

        assert result == {"success": True, "output": "3 commits rewritten"}
        assert mock_fn.call_args.kwargs["config_path"] == "/tmp/rewrites.json"

    @pytest.mark.asyncio
    @patch("dev10x.git.mass_rewrite", new_callable=AsyncMock)
    async def test_returns_error_on_failure(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = err("config file not found")

        result = await cli_server.mass_rewrite(config_path="/tmp/missing.json")

        assert "error" in result

    @pytest.mark.asyncio
    @patch("dev10x.git.mass_rewrite", new_callable=AsyncMock)
    async def test_forwards_cwd(self, mock_fn: AsyncMock, tmp_path) -> None:
        mock_fn.return_value = ok({"success": True, "output": ""})

        with patch("dev10x.subprocess_utils.use_cwd") as mock_use_cwd:
            await cli_server.mass_rewrite(config_path="/tmp/x.json", cwd=str(tmp_path))

        mock_use_cwd.assert_called_once_with(str(tmp_path))


class TestStartSplitRebase:
    @pytest.mark.asyncio
    @patch("dev10x.git.start_split_rebase", new_callable=AsyncMock)
    async def test_delegates_to_git_module(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = ok({"success": True, "output": "rebase started"})

        result = await cli_server.start_split_rebase(commit_hash="abc1234")

        assert result == {"success": True, "output": "rebase started"}
        assert mock_fn.call_args.kwargs["commit_hash"] == "abc1234"

    @pytest.mark.asyncio
    @patch("dev10x.git.start_split_rebase", new_callable=AsyncMock)
    async def test_forwards_base_branch(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = ok({"success": True, "output": ""})

        await cli_server.start_split_rebase(commit_hash="abc1234", base_branch="main")

        assert mock_fn.call_args.kwargs["base_branch"] == "main"

    @pytest.mark.asyncio
    @patch("dev10x.git.start_split_rebase", new_callable=AsyncMock)
    async def test_returns_error_on_failure(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = err("commit not found")

        result = await cli_server.start_split_rebase(commit_hash="deadbeef")

        assert "error" in result

    @pytest.mark.asyncio
    @patch("dev10x.git.start_split_rebase", new_callable=AsyncMock)
    async def test_forwards_cwd(self, mock_fn: AsyncMock, tmp_path) -> None:
        mock_fn.return_value = ok({"success": True, "output": ""})

        with patch("dev10x.subprocess_utils.use_cwd") as mock_use_cwd:
            await cli_server.start_split_rebase(commit_hash="abc1234", cwd=str(tmp_path))

        mock_use_cwd.assert_called_once_with(str(tmp_path))


class TestNextWorktreeName:
    @pytest.mark.asyncio
    @patch("dev10x.git.next_worktree_name", new_callable=AsyncMock)
    async def test_delegates_to_git_module(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = ok({"path": "/work/.worktrees/proj-02"})

        result = await cli_server.next_worktree_name()

        assert result == {"path": "/work/.worktrees/proj-02"}
        assert mock_fn.call_args.kwargs["base_dir"] is None

    @pytest.mark.asyncio
    @patch("dev10x.git.next_worktree_name", new_callable=AsyncMock)
    async def test_forwards_base_dir(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = ok({"path": "/custom/.worktrees/proj-01"})

        await cli_server.next_worktree_name(base_dir="/custom/.worktrees")

        assert mock_fn.call_args.kwargs["base_dir"] == "/custom/.worktrees"

    @pytest.mark.asyncio
    @patch("dev10x.git.next_worktree_name", new_callable=AsyncMock)
    async def test_returns_error_on_failure(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = err("no repo found")

        result = await cli_server.next_worktree_name()

        assert "error" in result

    @pytest.mark.asyncio
    @patch("dev10x.git.next_worktree_name", new_callable=AsyncMock)
    async def test_forwards_cwd(self, mock_fn: AsyncMock, tmp_path) -> None:
        mock_fn.return_value = ok({"path": "/work/.worktrees/proj-01"})

        with patch("dev10x.subprocess_utils.use_cwd") as mock_use_cwd:
            await cli_server.next_worktree_name(cwd=str(tmp_path))

        mock_use_cwd.assert_called_once_with(str(tmp_path))


class TestSetupAliases:
    @pytest.mark.asyncio
    @patch("dev10x.git.setup_aliases", new_callable=AsyncMock)
    async def test_delegates_to_git_module(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = ok({"success": True, "output": "aliases set"})

        result = await cli_server.setup_aliases()

        assert result == {"success": True, "output": "aliases set"}
        mock_fn.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("dev10x.git.setup_aliases", new_callable=AsyncMock)
    async def test_returns_error_on_failure(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = err("git config failed")

        result = await cli_server.setup_aliases()

        assert "error" in result
