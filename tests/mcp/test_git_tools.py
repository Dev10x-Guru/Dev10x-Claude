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

    @pytest.mark.asyncio
    @patch("dev10x.git.create_worktree", new_callable=AsyncMock)
    @patch("dev10x.skills.permission.update_paths.find_config")
    @patch("dev10x.skills.permission.update_paths.load_config")
    @patch("dev10x.skills.permission.update_paths.seed_worktree")
    async def test_seed_success_adds_seeded_permissions(
        self,
        mock_seed: AsyncMock,
        mock_load: AsyncMock,
        mock_find: AsyncMock,
        mock_create: AsyncMock,
    ) -> None:
        from dev10x.domain.common.result import ok as domain_ok

        mock_create.return_value = ok(
            {"worktree_path": "/tmp/wt", "branch": "feat", "created": True}
        )
        mock_find.return_value = domain_ok("/fake/config.yaml")
        mock_load.return_value = {"base_permissions": ["Bash(git)"]}
        mock_seed.return_value = domain_ok(
            {"added": 3, "path": "/tmp/wt/.claude/settings.local.json"}
        )

        result = await cli_server.create_worktree(branch="feat")

        assert result.get("seeded_permissions") == 3

    @pytest.mark.asyncio
    @patch("dev10x.git.create_worktree", new_callable=AsyncMock)
    @patch("dev10x.skills.permission.update_paths.find_config")
    async def test_seed_skipped_when_find_config_fails(
        self,
        mock_find: AsyncMock,
        mock_create: AsyncMock,
    ) -> None:
        from dev10x.domain.common.result import err as domain_err

        mock_create.return_value = ok(
            {"worktree_path": "/tmp/wt", "branch": "feat", "created": True}
        )
        mock_find.return_value = domain_err("config not found")

        result = await cli_server.create_worktree(branch="feat")

        # No seed keys when config lookup fails — creation still succeeds.
        assert "error" not in result
        assert "seeded_permissions" not in result
        assert "seed_error" not in result

    @pytest.mark.asyncio
    @patch("dev10x.git.create_worktree", new_callable=AsyncMock)
    @patch("dev10x.skills.permission.update_paths.find_config")
    @patch("dev10x.skills.permission.update_paths.load_config")
    @patch("dev10x.skills.permission.update_paths.seed_worktree")
    async def test_seed_failure_records_seed_error_not_error(
        self,
        mock_seed: AsyncMock,
        mock_load: AsyncMock,
        mock_find: AsyncMock,
        mock_create: AsyncMock,
    ) -> None:
        from dev10x.domain.common.result import err as domain_err
        from dev10x.domain.common.result import ok as domain_ok

        mock_create.return_value = ok(
            {"worktree_path": "/tmp/wt", "branch": "feat", "created": True}
        )
        mock_find.return_value = domain_ok("/fake/config.yaml")
        mock_load.return_value = {}
        mock_seed.return_value = domain_err("permission denied writing settings")

        result = await cli_server.create_worktree(branch="feat")

        # Seed failure must not shadow the successful worktree creation.
        assert "error" not in result
        assert result.get("seed_error") == "permission denied writing settings"

    @pytest.mark.asyncio
    @patch("dev10x.git.create_worktree", new_callable=AsyncMock)
    @patch("dev10x.skills.permission.update_paths.find_config")
    async def test_oserror_during_seed_records_seed_error(
        self,
        mock_find: AsyncMock,
        mock_create: AsyncMock,
    ) -> None:

        mock_create.return_value = ok(
            {"worktree_path": "/tmp/wt", "branch": "feat", "created": True}
        )
        mock_find.side_effect = OSError("disk full")

        result = await cli_server.create_worktree(branch="feat")

        assert "error" not in result
        assert "disk full" in result.get("seed_error", "")

    @pytest.mark.asyncio
    @patch("dev10x.git.create_worktree", new_callable=AsyncMock)
    async def test_seed_skipped_when_result_has_error(self, mock_create: AsyncMock) -> None:
        mock_create.return_value = err("branch already checked out")

        result = await cli_server.create_worktree(branch="feature")

        # An error result must not trigger seeding and must not gain a seed_error key.
        assert "error" in result
        assert "seeded_permissions" not in result
        assert "seed_error" not in result

    @pytest.mark.asyncio
    @patch("dev10x.git.create_worktree", new_callable=AsyncMock)
    async def test_seed_skipped_when_worktree_path_absent(self, mock_create: AsyncMock) -> None:
        # git module may return a payload without worktree_path on certain code-paths.
        mock_create.return_value = ok({"branch": "feat", "created": True})

        result = await cli_server.create_worktree(branch="feat")

        assert "seeded_permissions" not in result
        assert "seed_error" not in result


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
