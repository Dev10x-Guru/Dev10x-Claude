"""Tests for servers/cli_server.py core infrastructure and tools.

This file covers the helper functions and a representative sample
of MCP tools. Full 100% coverage of all 21 tools is tracked in
GH-493 and will be completed incrementally.
"""

from __future__ import annotations

import json
import subprocess
from unittest.mock import AsyncMock, patch

import pytest

from dev10x.domain.common.repository_ref import RepositoryRef
from dev10x.domain.common.result import ErrorResult, SuccessResult, err, ok

cli_server = pytest.importorskip("dev10x.mcp.server_cli", reason="mcp not installed")

gh = pytest.importorskip("dev10x.github", reason="dev10x not installed")


@pytest.fixture
def mock_resolve_repo():
    with patch.object(
        gh,
        "_resolve_repo",
        new_callable=AsyncMock,
        return_value=ok(RepositoryRef(owner="owner", name="repo")),
    ) as mock:
        yield mock


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
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_returns_repo_on_success(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="Dev10x-Guru/dev10x-claude\n")

        result = await gh._detect_repo()

        assert result == "Dev10x-Guru/dev10x-claude"

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_returns_none_on_failure(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="not a git repo")

        result = await gh._detect_repo()

        assert result is None


class TestGhApi:
    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
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
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
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
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
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
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
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
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
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
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
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
        "dev10x.github._detect_repo",
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
    @patch("dev10x.github._detect_repo", new_callable=AsyncMock, return_value=None)
    async def test_returns_error_when_detection_fails(
        self,
        _mock: AsyncMock,
    ) -> None:
        result = await gh._resolve_repo(repo=None)

        assert isinstance(result, ErrorResult)
        assert "repository" in result.error.lower()


class TestDetectTracker:
    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
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
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
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
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
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
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
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
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="Permission denied")

        result = await cli_server.issue_create(title="Test")

        assert "error" in result

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_falls_back_to_key_value_on_bad_json(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="NUMBER=789\nTITLE=Test")

        result = await cli_server.issue_create(title="Test")

        assert result["NUMBER"] == "789"

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
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
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
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
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
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
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
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
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
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
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_runs_quality_checks_successfully(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="All checks passed")

        result = await cli_server.pre_pr_checks()

        assert result["success"] is True
        assert result["output"] == "All checks passed"

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
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


# ── MCP handler coverage (GH-79 #G1, #G2b) ──────────────────────


class TestPrCommentReply:
    """#G2b — MCP handler must propagate as_bot=True down to _gh_api."""

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_propagates_as_bot_true_to_gh_api(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(stdout=json.dumps({"id": 999}))

        result = await cli_server.pr_comment_reply(
            pr_number=42,
            comment_id=123,
            body="reply text",
        )

        assert "error" not in result
        mock_api.assert_called_once()
        assert mock_api.call_args.kwargs["as_bot"] is True

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_returns_error_dict_on_api_failure(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(returncode=1, stderr="Not Found")

        result = await cli_server.pr_comment_reply(
            pr_number=42,
            comment_id=123,
            body="x",
        )

        assert "error" in result


class TestPrComments:
    @pytest.mark.asyncio
    @patch("dev10x.github.pr_comments", new_callable=AsyncMock)
    async def test_delegates_to_github_module(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = ok({"comments": []})

        result = await cli_server.pr_comments(action="list", pr_number=42)

        assert result == {"comments": []}
        assert mock_fn.call_args.kwargs["action"] == "list"
        assert mock_fn.call_args.kwargs["pr_number"] == 42

    @pytest.mark.asyncio
    @patch("dev10x.github.pr_comments", new_callable=AsyncMock)
    async def test_returns_error_dict_on_failure(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = err("invalid action")

        result = await cli_server.pr_comments(action="bogus")

        assert "error" in result


class TestPostSummaryCommentMcp:
    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    @patch("dev10x.github._bot_env", new_callable=AsyncMock, return_value=None)
    @patch("dev10x.github._detect_repo", new_callable=AsyncMock, return_value="owner/repo")
    async def test_posts_summary(
        self,
        _mock_repo: AsyncMock,
        _mock_bot_env: AsyncMock,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="posted")

        result = await cli_server.post_summary_comment(
            issue_id="GH-79",
            summary_text="- summary",
        )

        assert result["success"] is True

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    @patch("dev10x.github._bot_env", new_callable=AsyncMock, return_value=None)
    @patch("dev10x.github._detect_repo", new_callable=AsyncMock, return_value="owner/repo")
    async def test_returns_error_on_failure(
        self,
        _mock_repo: AsyncMock,
        _mock_bot_env: AsyncMock,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="boom")

        result = await cli_server.post_summary_comment(issue_id="GH-1", summary_text="x")

        assert "error" in result


class TestCreatePrMcp:
    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_creates_pr_returns_number_and_url(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(
            stdout="https://github.com/o/r/pull/7\n7",
        )

        result = await cli_server.create_pr(title="t", job_story="js", issue_id="GH-1")

        assert result["pr_number"] == 7
        assert "github.com" in result["url"]

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="no branch")

        result = await cli_server.create_pr(title="t", job_story="js", issue_id="GH-1")

        assert "error" in result


class TestUpdatePrMcp:
    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api", new_callable=AsyncMock)
    async def test_updates_body(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo: AsyncMock,
    ) -> None:
        mock_api.return_value = _completed(stdout="{}")

        result = await cli_server.update_pr(pr_number=1, body="new")

        assert result["pr_number"] == 1
        assert "url" in result

    @pytest.mark.asyncio
    async def test_returns_error_when_no_fields(self) -> None:
        result = await cli_server.update_pr(pr_number=1)

        assert "error" in result


class TestMergePrMcp:
    @pytest.mark.asyncio
    @patch("dev10x.github.merge_pr", new_callable=AsyncMock)
    async def test_delegates_to_github_module(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = ok(
            {
                "pr_number": 42,
                "url": "https://github.com/o/r/pull/42",
                "strategy": "rebase",
                "branch_deleted": True,
                "repo": "o/r",
            }
        )

        result = await cli_server.merge_pr(pr_number=42)

        assert result["pr_number"] == 42
        assert result["strategy"] == "rebase"
        assert mock_fn.call_args.kwargs == {
            "pr_number": 42,
            "strategy": "rebase",
            "delete_branch": True,
            "repo": None,
        }

    @pytest.mark.asyncio
    @patch("dev10x.github.merge_pr", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = err("not mergeable")

        result = await cli_server.merge_pr(pr_number=42)

        assert "error" in result


class TestGenerateCommitListMcp:
    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_returns_commit_list(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="- abc First\n- def Second\n")

        result = await cli_server.generate_commit_list(pr_number=42)

        assert "commit_list" in result
        assert "First" in result["commit_list"]

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="no commits")

        result = await cli_server.generate_commit_list(pr_number=42)

        assert "error" in result


class TestPushSafe:
    @pytest.mark.asyncio
    @patch("dev10x.git.push_safe", new_callable=AsyncMock)
    async def test_delegates_to_git_module(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = ok({"success": True, "branch": "feature"})

        result = await cli_server.push_safe(args=["origin", "feature"])

        assert result["success"] is True
        assert mock_fn.call_args.kwargs["args"] == ["origin", "feature"]

    @pytest.mark.asyncio
    @patch("dev10x.git.push_safe", new_callable=AsyncMock)
    async def test_returns_error_when_blocked(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = err("protected branch")

        result = await cli_server.push_safe(args=["origin", "main"])

        assert "error" in result


class TestPrNotify:
    @pytest.mark.asyncio
    @patch("dev10x.github.pr_notify", new_callable=AsyncMock)
    async def test_delegates_with_action_prepare(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = ok({"prepared": True})

        result = await cli_server.pr_notify(pr_number=1, repo="o/r")

        assert result == {"prepared": True}
        assert mock_fn.call_args.kwargs["action"] == "prepare"

    @pytest.mark.asyncio
    @patch("dev10x.github.pr_notify", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = err("script missing")

        result = await cli_server.pr_notify(pr_number=1, repo="o/r")

        assert "error" in result


class TestCheckTopLevelComments:
    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_returns_findings_and_count(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout=json.dumps([{"id": 1}, {"id": 2}]))

        result = await cli_server.check_top_level_comments(pr_number=42, repo="o/r")

        assert result["count"] == 2

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_returns_error_on_invalid_json(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="not json")

        result = await cli_server.check_top_level_comments(pr_number=42, repo="o/r")

        assert "error" in result


class TestUnresolvedThreadsMcp:
    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_returns_prs_and_count(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout=json.dumps([{"number": 1}]))

        result = await cli_server.unresolved_threads(repo="o/r")

        assert result["count"] == 1

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="rate limit")

        result = await cli_server.unresolved_threads(repo="o/r")

        assert "error" in result


class TestIssueGet:
    @pytest.mark.asyncio
    @patch("dev10x.github.issue_get", new_callable=AsyncMock)
    async def test_delegates_to_github_module(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = ok({"title": "T", "state": "OPEN"})

        result = await cli_server.issue_get(number=1, repo="o/r")

        assert result["title"] == "T"
        assert mock_fn.call_args.kwargs == {"number": 1, "repo": "o/r"}

    @pytest.mark.asyncio
    @patch("dev10x.github.issue_get", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = err("Not Found")

        result = await cli_server.issue_get(number=999)

        assert "error" in result


class TestPrGet:
    @pytest.mark.asyncio
    @patch("dev10x.github.pr_get", new_callable=AsyncMock)
    async def test_delegates_to_github_module(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = ok(
            {
                "number": 42,
                "title": "T",
                "state": "OPEN",
                "merged": False,
            }
        )

        result = await cli_server.pr_get(number=42, repo="o/r")

        assert result["number"] == 42
        assert result["state"] == "OPEN"
        assert mock_fn.call_args.kwargs == {"number": 42, "repo": "o/r"}

    @pytest.mark.asyncio
    @patch("dev10x.github.pr_get", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = err("Not Found")

        result = await cli_server.pr_get(number=999)

        assert "error" in result


class TestIssueClose:
    @pytest.mark.asyncio
    @patch("dev10x.github.issue_close", new_callable=AsyncMock)
    async def test_delegates_to_github_module(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = ok({"number": 1, "state": "closed", "url": "https://example/1"})

        result = await cli_server.issue_close(
            number=1,
            reason="not_planned",
            repo="o/r",
        )

        assert result["state"] == "closed"
        assert mock_fn.call_args.kwargs == {
            "number": 1,
            "reason": "not_planned",
            "comment": None,
            "repo": "o/r",
        }

    @pytest.mark.asyncio
    @patch("dev10x.github.issue_close", new_callable=AsyncMock)
    async def test_passes_comment(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = ok({"number": 1, "state": "closed", "url": "https://example/1"})

        await cli_server.issue_close(number=1, comment="thanks", repo="o/r")

        assert mock_fn.call_args.kwargs["comment"] == "thanks"

    @pytest.mark.asyncio
    @patch("dev10x.github.issue_close", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = err("Not Found")

        result = await cli_server.issue_close(number=999)

        assert "error" in result


class TestIssueReopen:
    @pytest.mark.asyncio
    @patch("dev10x.github.issue_reopen", new_callable=AsyncMock)
    async def test_delegates_to_github_module(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = ok({"number": 1, "state": "open", "url": "https://example/1"})

        result = await cli_server.issue_reopen(number=1, repo="o/r")

        assert result["state"] == "open"
        assert mock_fn.call_args.kwargs == {"number": 1, "repo": "o/r"}

    @pytest.mark.asyncio
    @patch("dev10x.github.issue_reopen", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = err("Not Found")

        result = await cli_server.issue_reopen(number=999)

        assert "error" in result


class TestIssueComments:
    @pytest.mark.asyncio
    @patch("dev10x.github.issue_comments", new_callable=AsyncMock)
    async def test_returns_comment_list(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = ok({"comments": [{"id": 1}]})

        result = await cli_server.issue_comments(number=1, repo="o/r")

        assert result == {"comments": [{"id": 1}]}

    @pytest.mark.asyncio
    @patch("dev10x.github.issue_comments", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = err("Not Found")

        result = await cli_server.issue_comments(number=999)

        assert "error" in result


class TestStartSplitRebase:
    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    async def test_starts_rebase(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="SUCCESS=true")

        result = await cli_server.start_split_rebase(commit_hash="abc1234")

        assert isinstance(result, dict)

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="dirty tree")

        result = await cli_server.start_split_rebase(commit_hash="abc1234")

        assert "error" in result


class TestMassRewrite:
    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    async def test_rewrites_with_config(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="ok")

        result = await cli_server.mass_rewrite(config_path="/tmp/rewrite.json")

        assert isinstance(result, dict)

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="bad config")

        result = await cli_server.mass_rewrite(config_path="/tmp/x.json")

        assert "error" in result


class TestPlanSyncSetContext:
    @pytest.mark.asyncio
    @patch("dev10x.plan.set_context", new_callable=AsyncMock)
    async def test_delegates_to_plan_module(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = ok({"success": True, "updated_keys": ["x"]})

        result = await cli_server.plan_sync_set_context(args=["x=1"])

        assert result["success"] is True
        assert mock_fn.call_args.kwargs["args"] == ["x=1"]


class TestPlanSyncJsonSummary:
    @pytest.mark.asyncio
    @patch("dev10x.plan.json_summary", new_callable=AsyncMock)
    async def test_returns_summary(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = ok({"tasks": []})

        result = await cli_server.plan_sync_json_summary()

        assert result == {"tasks": []}


class TestPlanSyncArchive:
    @pytest.mark.asyncio
    @patch("dev10x.plan.archive", new_callable=AsyncMock)
    async def test_archives_plan(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = ok({"success": True, "archive_name": "plan-2026-01-01.md"})

        result = await cli_server.plan_sync_archive()

        assert result["success"] is True


class TestGenerateSkillIndex:
    @pytest.mark.asyncio
    @patch("dev10x.skill_index.generate_all", new_callable=AsyncMock)
    async def test_generates_index(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = ok({"success": True, "output": "done"})

        result = await cli_server.generate_skill_index()

        assert result["success"] is True
        assert mock_fn.call_args.kwargs == {"force": False}

    @pytest.mark.asyncio
    @patch("dev10x.skill_index.generate_all", new_callable=AsyncMock)
    async def test_passes_force_flag(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = ok({"success": True})

        await cli_server.generate_skill_index(force=True)

        assert mock_fn.call_args.kwargs == {"force": True}


class TestAuditExtractSession:
    @pytest.mark.asyncio
    @patch("dev10x.audit.extract_session", new_callable=AsyncMock)
    async def test_extracts_session(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = ok({"success": True, "output": "extracted"})

        result = await cli_server.audit_extract_session(jsonl_path="/tmp/x.jsonl")

        assert result["success"] is True


class TestAuditAnalyzeActions:
    @pytest.mark.asyncio
    @patch("dev10x.audit.analyze_actions", new_callable=AsyncMock)
    async def test_analyzes_actions(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = ok({"success": True})

        result = await cli_server.audit_analyze_actions(transcript_path="/tmp/x.md")

        assert result["success"] is True


class TestAuditAnalyzePermissions:
    @pytest.mark.asyncio
    @patch("dev10x.audit.analyze_permissions", new_callable=AsyncMock)
    async def test_analyzes_permissions(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = ok({"success": True})

        result = await cli_server.audit_analyze_permissions(transcript_path="/tmp/x.md")

        assert result["success"] is True


class TestAuditHookLogPath:
    @pytest.mark.asyncio
    @patch("dev10x.audit.hook_log_path", new_callable=AsyncMock)
    async def test_returns_log_path(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = ok(
            {
                "audit_dir": "/tmp/Dev10x/hook-audit",
                "today_log": "/tmp/Dev10x/hook-audit/2026-01-01.jsonl",
                "today_log_exists": False,
                "audit_dir_exists": True,
                "available_logs": [],
                "audit_disabled": False,
            }
        )

        result = await cli_server.audit_hook_log_path()

        assert "audit_dir" in result


class TestAuditHookRecent:
    @pytest.mark.asyncio
    @patch("dev10x.audit.hook_recent", new_callable=AsyncMock)
    async def test_returns_recent_records(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = ok(
            {
                "log_path": "/tmp/x.jsonl",
                "exists": True,
                "count": 0,
                "records": [],
            }
        )

        result = await cli_server.audit_hook_recent(limit=10)

        assert result["count"] == 0
        assert mock_fn.call_args.kwargs["limit"] == 10


# ── #G1b: cwd activation per CWD-sensitive handler ──────────────


CWD_HANDLERS: list[tuple[str, dict]] = [
    (
        "detect_tracker",
        {"ticket_id": "GH-1"},
    ),
    (
        "pr_detect",
        {"arg": "#1"},
    ),
    (
        "issue_get",
        {"number": 1},
    ),
    (
        "issue_comments",
        {"number": 1},
    ),
    (
        "issue_create",
        {"title": "t"},
    ),
    (
        "pr_comments",
        {"action": "list", "pr_number": 1},
    ),
    (
        "verify_pr_state",
        {},
    ),
    (
        "pre_pr_checks",
        {},
    ),
    (
        "generate_commit_list",
        {"pr_number": 1},
    ),
    (
        "post_summary_comment",
        {"issue_id": "GH-1", "summary_text": "x"},
    ),
    (
        "check_top_level_comments",
        {"pr_number": 1, "repo": "o/r"},
    ),
    (
        "unresolved_threads",
        {"repo": "o/r"},
    ),
    (
        "rebase_groom",
        {"seq_path": "/tmp/seq", "base_ref": "develop"},
    ),
    (
        "create_worktree",
        {"branch": "feature"},
    ),
    (
        "mass_rewrite",
        {"config_path": "/tmp/x.json"},
    ),
    (
        "start_split_rebase",
        {"commit_hash": "abc1234"},
    ),
    (
        "next_worktree_name",
        {},
    ),
    (
        "plan_sync_json_summary",
        {},
    ),
    (
        "plan_sync_archive",
        {},
    ),
    (
        "pr_get",
        {"number": 1},
    ),
    (
        "issue_close",
        {"number": 1},
    ),
    (
        "issue_reopen",
        {"number": 1},
    ),
]


class TestCwdParameterActivation:
    """#G1b — every CWD-sensitive MCP handler must invoke use_cwd(cwd)."""

    @pytest.mark.parametrize(
        "handler_name,kwargs",
        CWD_HANDLERS,
        ids=[h for h, _ in CWD_HANDLERS],
    )
    @pytest.mark.asyncio
    async def test_use_cwd_activates_when_cwd_passed(
        self,
        handler_name: str,
        kwargs: dict,
        tmp_path,
    ) -> None:
        handler = getattr(cli_server, handler_name)

        with patch("dev10x.subprocess_utils.use_cwd") as mock_use_cwd:
            try:
                await handler(**kwargs, cwd=str(tmp_path))
            except Exception:
                # The handler's underlying call may fail (no real
                # subprocess); we only care that use_cwd was entered.
                pass

        mock_use_cwd.assert_called_once_with(str(tmp_path))


# ── GH-247 G1: four untested delegation handlers ─────────────────


class TestPrIssueComment:
    @pytest.mark.asyncio
    @patch("dev10x.github.pr_issue_comment", new_callable=AsyncMock)
    async def test_delegates_to_github_module(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = ok({"id": 1, "body": "hello", "created_at": "2026-01-01"})

        result = await cli_server.pr_issue_comment(
            pr_number=42,
            body="hello",
            repo="o/r",
        )

        assert result == {"id": 1, "body": "hello", "created_at": "2026-01-01"}
        assert mock_fn.call_args.kwargs == {
            "pr_number": 42,
            "body": "hello",
            "repo": "o/r",
        }

    @pytest.mark.asyncio
    @patch("dev10x.github.pr_issue_comment", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = err("Not Found")

        result = await cli_server.pr_issue_comment(pr_number=99, body="x")

        assert "error" in result

    @pytest.mark.asyncio
    @patch("dev10x.github.pr_issue_comment", new_callable=AsyncMock)
    async def test_forwards_repo_none_when_omitted(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = ok({"id": 2, "body": "y", "created_at": "2026-01-01"})

        await cli_server.pr_issue_comment(pr_number=1, body="y")

        assert mock_fn.call_args.kwargs["repo"] is None


class TestMinimizeComments:
    @pytest.mark.asyncio
    @patch("dev10x.github.minimize_comments", new_callable=AsyncMock)
    async def test_delegates_to_github_module(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = ok({"m0": {"isMinimized": True}})

        result = await cli_server.minimize_comments(
            node_ids=["PRRC_abc"],
            classifier="RESOLVED",
            repo="o/r",
        )

        assert result == {"m0": {"isMinimized": True}}
        assert mock_fn.call_args.kwargs == {
            "node_ids": ["PRRC_abc"],
            "classifier": "RESOLVED",
            "repo": "o/r",
        }

    @pytest.mark.asyncio
    @patch("dev10x.github.minimize_comments", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = err("GraphQL error")

        result = await cli_server.minimize_comments(node_ids=["PRRC_bad"])

        assert "error" in result

    @pytest.mark.asyncio
    @patch("dev10x.github.minimize_comments", new_callable=AsyncMock)
    async def test_forwards_default_classifier_outdated(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = ok({"m0": {"isMinimized": True}})

        await cli_server.minimize_comments(node_ids=["PRRC_x"])

        assert mock_fn.call_args.kwargs["classifier"] == "OUTDATED"


class TestRequestReview:
    @pytest.mark.asyncio
    @patch("dev10x.github.request_review", new_callable=AsyncMock)
    async def test_delegates_to_github_module(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = ok({"requested_reviewers": ["alice"]})

        result = await cli_server.request_review(
            pr_number=42,
            reviewers=["alice"],
            team=False,
            repo="o/r",
        )

        assert result == {"requested_reviewers": ["alice"]}
        assert mock_fn.call_args.kwargs == {
            "pr_number": 42,
            "reviewers": ["alice"],
            "team": False,
            "repo": "o/r",
        }

    @pytest.mark.asyncio
    @patch("dev10x.github.request_review", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = err("Not Found")

        result = await cli_server.request_review(pr_number=99, reviewers=["x"])

        assert "error" in result

    @pytest.mark.asyncio
    @patch("dev10x.github.request_review", new_callable=AsyncMock)
    async def test_forwards_team_none_when_omitted(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = ok({"requested_reviewers": ["bob"]})

        await cli_server.request_review(pr_number=1, reviewers=["bob"])

        assert mock_fn.call_args.kwargs["team"] is None


class TestResolveReviewThread:
    @pytest.mark.asyncio
    @patch("dev10x.github.resolve_review_thread", new_callable=AsyncMock)
    async def test_delegates_to_github_module(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = ok({"t0": {"isResolved": True}})

        result = await cli_server.resolve_review_thread(
            thread_ids=["PRRT_abc"],
            comment_ids=None,
            repo="o/r",
        )

        assert result == {"t0": {"isResolved": True}}
        assert mock_fn.call_args.kwargs == {
            "thread_ids": ["PRRT_abc"],
            "comment_ids": None,
            "repo": "o/r",
        }

    @pytest.mark.asyncio
    @patch("dev10x.github.resolve_review_thread", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = err("GraphQL error")

        result = await cli_server.resolve_review_thread(thread_ids=["PRRT_bad"])

        assert "error" in result

    @pytest.mark.asyncio
    @patch("dev10x.github.resolve_review_thread", new_callable=AsyncMock)
    async def test_accepts_comment_ids_instead_of_thread_ids(
        self,
        mock_fn: AsyncMock,
    ) -> None:
        mock_fn.return_value = ok({"t0": {"isResolved": True}})

        await cli_server.resolve_review_thread(
            comment_ids=["PRRC_xyz"],
            repo="o/r",
        )

        assert mock_fn.call_args.kwargs["comment_ids"] == ["PRRC_xyz"]
        assert mock_fn.call_args.kwargs["thread_ids"] is None


# ── GH-247 G9: issue_create label forwarding ─────────────────────


class TestIssueCreateLabelForwarding:
    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_forwards_each_label_with_repeated_flag(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(
            stdout='{"number":1,"title":"t","url":"https://github.com/o/r/issues/1"}',
        )

        await cli_server.issue_create(title="t", labels=["bug", "urgent"])

        call_args = list(mock_run.call_args[0])
        label_indices = [i for i, v in enumerate(call_args) if v == "--label"]
        assert len(label_indices) == 2
        assert call_args[label_indices[0] + 1] == "bug"
        assert call_args[label_indices[1] + 1] == "urgent"

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_no_label_flag_when_labels_omitted(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(
            stdout='{"number":2,"title":"t","url":"https://github.com/o/r/issues/2"}',
        )

        await cli_server.issue_create(title="t")

        call_args = list(mock_run.call_args[0])
        assert "--label" not in call_args
