"""Progress & log notifications for long-running MCP tools (GH-342).

The four long-running tools — ``run_tests``, ``mass_rewrite``,
``rebase_groom``, ``create_pr`` — accept an optional FastMCP ``Context``
that FastMCP injects automatically. When present, each tool emits a
start ``report_progress(0, 100)`` + ``info`` notification before the
subprocess and a terminal ``report_progress(100, 100)`` + ``info``/
``log`` notification after it. When ``ctx`` is ``None`` (the default in
unit tests and for clients that do not send a progress token), the tool
behaves exactly as before — no notifications, same return payload.
"""

from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock, patch

import pytest

cli_server = pytest.importorskip("dev10x.mcp.server_cli", reason="mcp not installed")


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


@pytest.fixture
def ctx() -> AsyncMock:
    """A stand-in FastMCP Context with awaitable notification methods."""
    fake = AsyncMock()
    fake.report_progress = AsyncMock()
    fake.info = AsyncMock()
    fake.log = AsyncMock()
    return fake


class TestRunTestsNotifications:
    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_emits_start_and_done_progress(
        self,
        mock_run: AsyncMock,
        ctx: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="==== 5 passed in 0.1s ====")

        result = await cli_server.run_tests(ctx=ctx)

        assert result["passed"] == 5
        assert ctx.report_progress.await_count == 2
        first = ctx.report_progress.await_args_list[0].kwargs
        last = ctx.report_progress.await_args_list[1].kwargs
        assert first["progress"] == 0
        assert first["total"] == 100
        assert last["progress"] == 100
        assert last["total"] == 100
        ctx.info.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_failed_run_logs_warning(
        self,
        mock_run: AsyncMock,
        ctx: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(
            returncode=1,
            stdout="==== 1 failed, 2 passed in 0.1s ====",
        )

        await cli_server.run_tests(ctx=ctx)

        assert ctx.log.await_args.kwargs["level"] == "warning"

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_args_summarised_in_start_message(
        self,
        mock_run: AsyncMock,
        ctx: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="==== 1 passed in 0.1s ====")

        await cli_server.run_tests(args=["-k", "foo"], ctx=ctx)

        assert "-k foo" in ctx.report_progress.await_args_list[0].kwargs["message"]

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_no_notifications_without_ctx(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="==== 1 passed in 0.1s ====")

        result = await cli_server.run_tests()

        assert result["passed"] == 1


class TestRebaseGroomNotifications:
    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    async def test_success_emits_progress_and_info(
        self,
        mock_run: AsyncMock,
        ctx: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="SUCCESS=true\nCOMMITS_REWRITTEN=5")

        result = await cli_server.rebase_groom(
            seq_path="/tmp/seq",
            base_ref="develop",
            ctx=ctx,
        )

        assert "error" not in result
        assert ctx.report_progress.await_count == 2
        assert ctx.report_progress.await_args_list[1].kwargs["progress"] == 100
        assert ctx.info.await_count == 2

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    async def test_failure_logs_error(
        self,
        mock_run: AsyncMock,
        ctx: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="rebase blew up")

        result = await cli_server.rebase_groom(
            seq_path="/tmp/seq",
            base_ref="develop",
            ctx=ctx,
        )

        assert "error" in result
        assert ctx.log.await_args.kwargs["level"] == "error"

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    async def test_no_notifications_without_ctx(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="SUCCESS=true\nCOMMITS_REWRITTEN=1")

        result = await cli_server.rebase_groom(seq_path="/tmp/seq", base_ref="develop")

        assert isinstance(result, dict)


class TestMassRewriteNotifications:
    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    async def test_success_emits_progress_and_info(
        self,
        mock_run: AsyncMock,
        ctx: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="ok")

        result = await cli_server.mass_rewrite(config_path="/tmp/r.json", ctx=ctx)

        assert "error" not in result
        assert ctx.report_progress.await_count == 2
        assert ctx.info.await_count == 2

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    async def test_failure_logs_error(
        self,
        mock_run: AsyncMock,
        ctx: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="bad config")

        result = await cli_server.mass_rewrite(config_path="/tmp/x.json", ctx=ctx)

        assert "error" in result
        assert ctx.log.await_args.kwargs["level"] == "error"

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    async def test_no_notifications_without_ctx(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="ok")

        result = await cli_server.mass_rewrite(config_path="/tmp/r.json")

        assert isinstance(result, dict)


class TestCreatePrNotifications:
    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_success_emits_progress_and_info(
        self,
        mock_run: AsyncMock,
        ctx: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="https://github.com/o/r/pull/7\n7")

        result = await cli_server.create_pr(
            title="t",
            job_story="js",
            issue_id="GH-1",
            ctx=ctx,
        )

        assert result["pr_number"] == 7
        assert ctx.report_progress.await_count == 2
        assert "github.com" in ctx.report_progress.await_args_list[1].kwargs["message"]
        assert ctx.info.await_count == 2

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_failure_logs_error(
        self,
        mock_run: AsyncMock,
        ctx: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="no branch")

        result = await cli_server.create_pr(
            title="t",
            job_story="js",
            issue_id="GH-1",
            ctx=ctx,
        )

        assert "error" in result
        assert ctx.log.await_args.kwargs["level"] == "error"

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_no_notifications_without_ctx(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="https://github.com/o/r/pull/9\n9")

        result = await cli_server.create_pr(title="t", job_story="js", issue_id="GH-1")

        assert result["pr_number"] == 9
