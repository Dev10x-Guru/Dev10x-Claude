"""Tests for servers/cli_server.py core infrastructure and tools.

This file covers the helper functions and a representative sample
of MCP tools. Full 100% coverage of all 21 tools is tracked in
GH-493 and will be completed incrementally.
"""

from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock, patch

import pytest

from dev10x.domain.repository_ref import RepositoryRef
from dev10x.domain.result import ErrorResult, SuccessResult

cli_server = pytest.importorskip("dev10x.mcp.server_cli", reason="mcp not installed")

gh = pytest.importorskip("dev10x.mcp.github", reason="dev10x not installed")


def _completed(
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


class TestDetectRepo:
    @pytest.mark.asyncio
    @patch("dev10x.mcp.github.async_run", new_callable=AsyncMock)
    async def test_returns_repo_on_success(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="Dev10x-Guru/dev10x-claude\n")

        result = await gh._detect_repo()

        assert result == "Dev10x-Guru/dev10x-claude"

    @pytest.mark.asyncio
    @patch("dev10x.mcp.github.async_run", new_callable=AsyncMock)
    async def test_returns_none_on_failure(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="not a git repo")

        result = await gh._detect_repo()

        assert result is None


class TestGhApi:
    @pytest.mark.asyncio
    @patch("dev10x.mcp.github.async_run", new_callable=AsyncMock)
    async def test_builds_get_command(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="{}")

        await gh._gh_api(endpoint="/repos/owner/repo")

        cmd = mock_run.call_args.kwargs["args"]
        assert cmd[0] == "gh"
        assert cmd[1] == "api"
        assert "/repos/owner/repo" in cmd
        assert "-X" not in cmd

    @pytest.mark.asyncio
    @patch("dev10x.mcp.github.async_run", new_callable=AsyncMock)
    async def test_adds_method_for_non_get(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="{}")

        await gh._gh_api(endpoint="/repos/owner/repo/pulls", method="POST")

        cmd = mock_run.call_args.kwargs["args"]
        assert "-X" in cmd
        post_idx = cmd.index("-X")
        assert cmd[post_idx + 1] == "POST"

    @pytest.mark.asyncio
    @patch("dev10x.mcp.github.async_run", new_callable=AsyncMock)
    async def test_adds_jq_filter(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="value")

        await gh._gh_api(endpoint="/repos/owner/repo", jq=".name")

        cmd = mock_run.call_args.kwargs["args"]
        assert "--jq" in cmd
        jq_idx = cmd.index("--jq")
        assert cmd[jq_idx + 1] == ".name"

    @pytest.mark.asyncio
    @patch("dev10x.mcp.github.async_run", new_callable=AsyncMock)
    async def test_handles_string_fields(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="{}")

        await gh._gh_api(
            endpoint="/repos/owner/repo",
            method="POST",
            fields={"title": "My PR"},
        )

        cmd = mock_run.call_args.kwargs["args"]
        assert "-f" in cmd
        f_idx = cmd.index("-f")
        assert cmd[f_idx + 1] == "title=My PR"

    @pytest.mark.asyncio
    @patch("dev10x.mcp.github.async_run", new_callable=AsyncMock)
    async def test_handles_int_fields(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="{}")

        await gh._gh_api(
            endpoint="/repos/owner/repo",
            method="POST",
            fields={"count": 42},
        )

        cmd = mock_run.call_args.kwargs["args"]
        assert "-F" in cmd
        f_idx = cmd.index("-F")
        assert cmd[f_idx + 1] == "count=42"

    @pytest.mark.asyncio
    @patch("dev10x.mcp.github.async_run", new_callable=AsyncMock)
    async def test_handles_list_fields(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="{}")

        await gh._gh_api(
            endpoint="/repos/owner/repo",
            method="POST",
            fields={"reviewers": ["alice", "bob"]},
        )

        cmd = mock_run.call_args.kwargs["args"]
        assert "-f" in cmd
        f_indices = [i for i, c in enumerate(cmd) if c == "-f"]
        assert len(f_indices) == 2
        assert cmd[f_indices[0] + 1] == "reviewers[]=alice"
        assert cmd[f_indices[1] + 1] == "reviewers[]=bob"


class TestResolveRepo:
    @pytest.mark.asyncio
    async def test_returns_provided_repo(self) -> None:
        result = await gh._resolve_repo(repo="owner/repo")

        assert isinstance(result, SuccessResult)
        assert result.value == RepositoryRef(owner="owner", name="repo")

    @pytest.mark.asyncio
    @patch(
        "dev10x.mcp.github._detect_repo",
        new_callable=AsyncMock,
        return_value="detected/repo",
    )
    async def test_detects_repo_when_none_provided(
        self,
        _mock: AsyncMock,
    ) -> None:
        result = await gh._resolve_repo(repo=None)

        assert isinstance(result, SuccessResult)
        assert result.value == RepositoryRef(owner="detected", name="repo")

    @pytest.mark.asyncio
    @patch("dev10x.mcp.github._detect_repo", new_callable=AsyncMock, return_value=None)
    async def test_returns_error_when_detection_fails(
        self,
        _mock: AsyncMock,
    ) -> None:
        result = await gh._resolve_repo(repo=None)

        assert isinstance(result, ErrorResult)
        assert "repository" in result.error.lower()


class TestDetectTracker:
    @pytest.mark.asyncio
    @patch("dev10x.mcp.github.async_run_script", new_callable=AsyncMock)
    async def test_returns_parsed_output_on_success(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(
            stdout="TRACKER=github\nTICKET_ID=GH-15\nTICKET_NUMBER=15\nFIXES_URL=https://github.com/org/repo/issues/15",
        )

        result = await cli_server.detect_tracker(ticket_id="GH-15")

        assert result["TRACKER"] == "github"
        assert result["TICKET_NUMBER"] == "15"

    @pytest.mark.asyncio
    @patch("dev10x.mcp.github.async_run_script", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="Unknown tracker")

        result = await cli_server.detect_tracker(ticket_id="UNKNOWN-1")

        assert "error" in result


class TestMktmp:
    @pytest.mark.asyncio
    @patch("dev10x.utilities.async_run_script", new_callable=AsyncMock)
    async def test_returns_path_without_creating_file_by_default(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="/tmp/Dev10x/git/commit-msg.abc123.txt")

        result = await cli_server.mktmp(namespace="git", prefix="commit-msg", ext=".txt")

        assert result["path"] == "/tmp/Dev10x/git/commit-msg.abc123.txt"
        called_args = mock_run.call_args.args
        assert "--create" not in called_args
        assert "-d" not in called_args

    @pytest.mark.asyncio
    @patch("dev10x.utilities.async_run_script", new_callable=AsyncMock)
    async def test_passes_create_flag_when_requested(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="/tmp/Dev10x/git/legacy.abc.txt")

        await cli_server.mktmp(
            namespace="git",
            prefix="legacy",
            ext=".txt",
            create=True,
        )

        called_args = mock_run.call_args.args
        assert "--create" in called_args
        assert "-d" not in called_args

    @pytest.mark.asyncio
    @patch("dev10x.utilities.async_run_script", new_callable=AsyncMock)
    async def test_creates_temp_directory(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="/tmp/Dev10x/audit/session.abc123")

        result = await cli_server.mktmp(namespace="audit", prefix="session", directory=True)

        assert result["path"] == "/tmp/Dev10x/audit/session.abc123"
        called_args = mock_run.call_args.args
        assert "-d" in called_args
        assert "--create" not in called_args

    @pytest.mark.asyncio
    @patch("dev10x.utilities.async_run_script", new_callable=AsyncMock)
    async def test_directory_mode_ignores_create_flag(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="/tmp/Dev10x/audit/session.abc")

        await cli_server.mktmp(
            namespace="audit",
            prefix="session",
            directory=True,
            create=True,
        )

        called_args = mock_run.call_args.args
        assert "-d" in called_args
        assert "--create" not in called_args

    @pytest.mark.asyncio
    @patch("dev10x.utilities.async_run_script", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="Permission denied")

        result = await cli_server.mktmp(namespace="git", prefix="msg")

        assert "error" in result


class TestIssueCreate:
    @pytest.mark.asyncio
    @patch("dev10x.mcp.github.async_run_script", new_callable=AsyncMock)
    async def test_creates_issue_with_title_only(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(
            stdout='{"number":123,"title":"Fix bug","url":"https://github.com/org/repo/issues/123"}',
        )

        result = await cli_server.issue_create(title="Fix bug")

        assert result["number"] == 123
        assert result["title"] == "Fix bug"

    @pytest.mark.asyncio
    @patch("dev10x.mcp.github.async_run_script", new_callable=AsyncMock)
    async def test_creates_issue_with_body_and_labels(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(
            stdout='{"number":456,"title":"New feature","url":"https://github.com/org/repo/issues/456"}',
        )

        result = await cli_server.issue_create(
            title="New feature",
            body="Details here",
            labels=["enhancement", "priority"],
            repo="org/repo",
        )

        assert result["number"] == 456

    @pytest.mark.asyncio
    @patch("dev10x.mcp.github.async_run_script", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="Permission denied")

        result = await cli_server.issue_create(title="Test")

        assert "error" in result

    @pytest.mark.asyncio
    @patch("dev10x.mcp.github.async_run_script", new_callable=AsyncMock)
    async def test_falls_back_to_key_value_on_bad_json(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="NUMBER=789\nTITLE=Test")

        result = await cli_server.issue_create(title="Test")

        assert result["NUMBER"] == "789"

    @pytest.mark.asyncio
    @patch("dev10x.mcp.github.async_run_script", new_callable=AsyncMock)
    async def test_creates_issue_with_milestone(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(
            stdout='{"number":789,"title":"Track progress","url":"https://github.com/org/repo/issues/789"}',
        )

        result = await cli_server.issue_create(
            title="Track progress",
            milestone="v1.0",
        )

        assert result["number"] == 789
        call_args = list(mock_run.call_args[0])
        assert "--milestone" in call_args
        milestone_idx = call_args.index("--milestone")
        assert call_args[milestone_idx + 1] == "v1.0"


class TestPrDetect:
    @pytest.mark.asyncio
    @patch("dev10x.mcp.github.async_run_script", new_callable=AsyncMock)
    async def test_detects_pr_from_number(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(
            stdout="PR_NUMBER=123\nREPO=owner/repo\nBRANCH=feature/xyz\nSTATE=open\nHEAD_REF=feature/xyz",
        )

        result = await cli_server.pr_detect(arg="#123")

        assert "PR_NUMBER" in result

    @pytest.mark.asyncio
    @patch("dev10x.mcp.github.async_run_script", new_callable=AsyncMock)
    async def test_handles_detection_error(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="Invalid PR reference")

        result = await cli_server.pr_detect(arg="invalid")

        assert "error" in result


class TestNextWorktreeName:
    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    async def test_calculates_next_worktree_number(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="../.worktrees/project-05")

        result = await cli_server.next_worktree_name()

        assert "path" in result

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    async def test_handles_error_in_calculation(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="Failed to calculate")

        result = await cli_server.next_worktree_name()

        assert "error" in result


class TestSetupAliases:
    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    async def test_sets_up_git_aliases(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="Aliases configured")

        result = await cli_server.setup_aliases()

        assert isinstance(result, dict)
        assert result.get("success") is True

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    async def test_handles_alias_setup_error(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="Failed to configure")

        result = await cli_server.setup_aliases()

        assert "error" in result


class TestVerifyPrState:
    @pytest.mark.asyncio
    @patch("dev10x.mcp.github.async_run_script", new_callable=AsyncMock)
    async def test_verifies_pr_state_before_creation(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(
            stdout="BRANCH_NAME=feature/test\nISSUE=GH-123\nBASE_BRANCH=develop",
        )

        result = await cli_server.verify_pr_state()

        assert isinstance(result, dict)

    @pytest.mark.asyncio
    @patch("dev10x.mcp.github.async_run_script", new_callable=AsyncMock)
    async def test_blocks_pr_on_protected_branch(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(
            returncode=1,
            stderr="Cannot create PR from main branch",
        )

        result = await cli_server.verify_pr_state()

        assert "error" in result


class TestPrePrChecks:
    @pytest.mark.asyncio
    @patch("dev10x.mcp.github.async_run_script", new_callable=AsyncMock)
    async def test_runs_quality_checks_successfully(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="All checks passed")

        result = await cli_server.pre_pr_checks()

        assert result["success"] is True
        assert result["output"] == "All checks passed"

    @pytest.mark.asyncio
    @patch("dev10x.mcp.github.async_run_script", new_callable=AsyncMock)
    async def test_reports_check_failures(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="Linting failed")

        result = await cli_server.pre_pr_checks(base_branch="develop")

        assert "error" in result
        assert result["error"] == "Linting failed"


class TestRebaseGroom:
    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    async def test_rebases_and_grooms_commits(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="SUCCESS=true\nCOMMITS_REWRITTEN=5")

        result = await cli_server.rebase_groom(seq_path="/tmp/seq", base_ref="develop")

        assert isinstance(result, dict)


class TestCreateWorktree:
    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    async def test_creates_worktree(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(
            stdout="WORKTREE_PATH=../.worktrees/feature-01\nBRANCH=feature-branch\nCREATED=true",
        )

        result = await cli_server.create_worktree(branch="feature-branch")

        assert "WORKTREE_PATH" in result

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    async def test_handles_worktree_creation_error(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="Branch already exists")

        result = await cli_server.create_worktree(branch="existing-branch")

        assert "error" in result
