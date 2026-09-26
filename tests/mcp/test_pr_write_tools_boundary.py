"""Direct boundary-layer tests for the PR write MCP tools (GH-1449).

``create_pr``, ``update_pr``, and ``merge_pr`` previously had only
domain-layer coverage — ``tests/mcp/test_pr_lifecycle_tools.py``
exercises ``dev10x.github`` directly, never the registered MCP
handler. ``push_safe`` (``tests/mcp/test_git_tools.py``) and
``ci_check_status`` (``tests/mcp/test_monitor_tools.py``) already had
boundary coverage; the extra tests here round out the documented wire
shapes (GH-1424's push/CI payloads) rather than duplicate what those
files already assert.

Every test here asserts the wire payload (``to_wire()`` output) that
FastMCP actually hands back to a caller — a flattened ``dict``, never
a ``Result`` — per ``.claude/rules/mcp-tools.md`` § Tool Declaration
Pattern.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dev10x.domain.common.result import err, ok
from dev10x.mcp import server_cli as cli_server


class TestCreatePrBoundary:
    """``create_pr`` is a direct ``@server.tool()`` handler (not
    ``@github_tool``-wrapped) that calls ``to_wire()`` itself, so it
    needs its own boundary coverage rather than inheriting the
    decorator's."""

    @pytest.mark.asyncio
    @patch("dev10x.github.create_pr", new_callable=AsyncMock)
    async def test_returns_wire_payload_on_success(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = ok({"pr_number": 42, "url": "https://github.com/o/r/pull/42"})

        result = await cli_server.create_pr(title="t", issue_id="GH-1")

        assert result == {"pr_number": 42, "url": "https://github.com/o/r/pull/42"}

    @pytest.mark.asyncio
    @patch("dev10x.github.create_pr", new_callable=AsyncMock)
    async def test_returns_error_wire_payload_on_failure(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = err("job_story missing **When** marker")

        result = await cli_server.create_pr(title="t", issue_id="GH-1")

        assert result == {"error": "job_story missing **When** marker"}

    @pytest.mark.asyncio
    @patch("dev10x.github.create_pr", new_callable=AsyncMock)
    async def test_forwards_all_arguments(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = ok({"pr_number": 1, "url": "u"})

        await cli_server.create_pr(
            title="t",
            issue_id="GH-1",
            job_story="story",
            body=None,
            head="feature",
            milestone="M1",
            fixes_url="https://x",
            base_branch="develop",
            closes=[2, 3],
            draft=False,
            head_repo="fork-owner",
            repo="o/r",
        )

        assert mock_fn.call_args.kwargs == {
            "title": "t",
            "job_story": "story",
            "issue_id": "GH-1",
            "body": None,
            "head": "feature",
            "milestone": "M1",
            "fixes_url": "https://x",
            "base_branch": "develop",
            "closes": [2, 3],
            "draft": False,
            "head_repo": "fork-owner",
            "repo": "o/r",
        }

    @pytest.mark.asyncio
    @patch("dev10x.github.create_pr", new_callable=AsyncMock)
    async def test_enters_use_cwd_with_passed_cwd(self, mock_fn: AsyncMock, tmp_path) -> None:
        mock_fn.return_value = ok({"pr_number": 1, "url": "u"})

        with patch("dev10x.subprocess_utils.use_cwd") as mock_use_cwd:
            await cli_server.create_pr(title="t", issue_id="GH-1", cwd=str(tmp_path))

        mock_use_cwd.assert_called_once_with(str(tmp_path))

    @pytest.mark.asyncio
    @patch("dev10x.github.create_pr", new_callable=AsyncMock)
    async def test_reports_progress_and_info_when_ctx_present_on_success(
        self, mock_fn: AsyncMock
    ) -> None:
        mock_fn.return_value = ok({"pr_number": 7, "url": "https://github.com/o/r/pull/7"})
        ctx = MagicMock()
        ctx.report_progress = AsyncMock()
        ctx.info = AsyncMock()
        ctx.log = AsyncMock()

        await cli_server.create_pr(title="t", issue_id="GH-1", ctx=ctx)

        assert ctx.report_progress.await_count == 2
        assert ctx.info.await_count == 2
        ctx.log.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("dev10x.github.create_pr", new_callable=AsyncMock)
    async def test_logs_error_when_ctx_present_on_failure(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = err("issue_id required")
        ctx = MagicMock()
        ctx.report_progress = AsyncMock()
        ctx.info = AsyncMock()
        ctx.log = AsyncMock()

        await cli_server.create_pr(title="t", issue_id="GH-1", ctx=ctx)

        ctx.log.assert_awaited_once_with(level="error", message="create_pr: issue_id required")
        assert ctx.info.await_count == 1


class TestUpdatePrBoundary:
    @pytest.mark.asyncio
    @patch("dev10x.github.update_pr", new_callable=AsyncMock)
    async def test_returns_wire_payload_on_success(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = ok({"pr_number": 42, "url": "https://github.com/o/r/pull/42"})

        result = await cli_server.update_pr(pr_number=42, body="new body")

        assert result == {"pr_number": 42, "url": "https://github.com/o/r/pull/42"}

    @pytest.mark.asyncio
    @patch("dev10x.github.update_pr", new_callable=AsyncMock)
    async def test_returns_error_wire_payload_on_failure(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = err("at least one of body/title/base_branch/milestone required")

        result = await cli_server.update_pr(pr_number=42)

        assert result == {"error": "at least one of body/title/base_branch/milestone required"}

    @pytest.mark.asyncio
    @patch("dev10x.github.update_pr", new_callable=AsyncMock)
    async def test_forwards_all_arguments(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = ok({"pr_number": 42, "url": "u"})

        await cli_server.update_pr(
            pr_number=42,
            body="b",
            title="t",
            base_branch="develop",
            milestone="M1",
            repo="o/r",
        )

        assert mock_fn.call_args.kwargs == {
            "pr_number": 42,
            "body": "b",
            "title": "t",
            "base_branch": "develop",
            "milestone": "M1",
            "repo": "o/r",
        }

    @pytest.mark.asyncio
    @patch("dev10x.github.update_pr", new_callable=AsyncMock)
    async def test_enters_use_cwd_with_passed_cwd(self, mock_fn: AsyncMock, tmp_path) -> None:
        mock_fn.return_value = ok({"pr_number": 1, "url": "u"})

        with patch("dev10x.subprocess_utils.use_cwd") as mock_use_cwd:
            await cli_server.update_pr(pr_number=1, title="t", cwd=str(tmp_path))

        mock_use_cwd.assert_called_once_with(str(tmp_path))


class TestMergePrBoundary:
    @pytest.mark.asyncio
    @patch("dev10x.github.merge_pr", new_callable=AsyncMock)
    async def test_returns_wire_payload_on_success(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = ok(
            {
                "merged": True,
                "merged_as": "bot",
                "bot_fallback": None,
                "branch_deletion_error": None,
            }
        )

        result = await cli_server.merge_pr(pr_number=42)

        assert result == {
            "merged": True,
            "merged_as": "bot",
            "bot_fallback": None,
            "branch_deletion_error": None,
        }

    @pytest.mark.asyncio
    @patch("dev10x.github.merge_pr", new_callable=AsyncMock)
    async def test_returns_error_wire_payload_on_failure(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = err("Pull Request is still a draft")

        result = await cli_server.merge_pr(pr_number=42)

        assert result == {"error": "Pull Request is still a draft"}

    @pytest.mark.asyncio
    @patch("dev10x.github.merge_pr", new_callable=AsyncMock)
    async def test_forwards_all_arguments(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = ok({"merged": True, "merged_as": "engineer"})

        await cli_server.merge_pr(
            pr_number=42,
            strategy="squash",
            delete_branch=False,
            admin=True,
            auto=True,
            repo="o/r",
            expected_head_sha="deadbeef",
            use_bot=True,
        )

        assert mock_fn.call_args.kwargs == {
            "pr_number": 42,
            "strategy": "squash",
            "delete_branch": False,
            "admin": True,
            "auto": True,
            "repo": "o/r",
            "expected_head_sha": "deadbeef",
            "use_bot": True,
        }

    @pytest.mark.asyncio
    @patch("dev10x.github.merge_pr", new_callable=AsyncMock)
    async def test_enters_use_cwd_with_passed_cwd(self, mock_fn: AsyncMock, tmp_path) -> None:
        mock_fn.return_value = ok({"merged": True, "merged_as": "engineer"})

        with patch("dev10x.subprocess_utils.use_cwd") as mock_use_cwd:
            await cli_server.merge_pr(pr_number=1, cwd=str(tmp_path))

        mock_use_cwd.assert_called_once_with(str(tmp_path))


class TestPushSafeWireShape:
    """Supplementary to ``tests/mcp/test_git_tools.py::TestPushSafe`` —
    pins the full GH-1424 payload shape rather than a partial assert."""

    @pytest.mark.asyncio
    @patch("dev10x.git.push_safe", new_callable=AsyncMock)
    async def test_full_blocked_payload_passes_through_unmodified(
        self, mock_fn: AsyncMock
    ) -> None:
        mock_fn.return_value = ok({"pushed": False, "blocked_reason": "base_behind_remote"})

        result = await cli_server.push_safe(args=["--force-with-lease", "origin", "main"])

        assert result == {"pushed": False, "blocked_reason": "base_behind_remote"}


class TestCiCheckStatusWireShape:
    """Supplementary to ``tests/mcp/test_monitor_tools.py`` — pins the
    full GH-1376 corroboration fields rather than a partial assert."""

    @pytest.mark.asyncio
    @patch("dev10x.monitor.ci_check_status", new_callable=AsyncMock)
    async def test_full_verdict_payload_passes_through_unmodified(
        self, mock_fn: AsyncMock
    ) -> None:
        mock_fn.return_value = ok(
            {
                "verdict": "green",
                "required_verdict": "empty",
                "checks_source": "confirmed-zero",
                "pending": 0,
            }
        )

        result = await cli_server.ci_check_status(pr_number=42, repo="o/r", required_only=True)

        assert result == {
            "verdict": "green",
            "required_verdict": "empty",
            "checks_source": "confirmed-zero",
            "pending": 0,
        }
