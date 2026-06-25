from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock, patch

import pytest

from dev10x import runner
from dev10x.domain.common.result import ErrorResult, SuccessResult


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


# jest writes its summary to stderr.
JEST_PASS_STDERR = (
    "Test Suites: 3 passed, 3 total\n"
    "Tests:       7 passed, 7 total\n"
    "Snapshots:   0 total\n"
    "Time:        1.23 s\n"
)

JEST_FAIL_STDERR = (
    "Test Suites: 1 failed, 2 passed, 3 total\n"
    "Tests:       2 failed, 1 skipped, 7 passed, 10 total\n"
    "Time:        2.10 s\n"
)


class TestRunNodeTests:
    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_jest_is_default_with_coverage(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(stderr=JEST_PASS_STDERR)

        result = await runner.run_node_tests()

        assert isinstance(result, SuccessResult)
        called_args = mock_run.call_args.kwargs["args"]
        assert called_args == ["npx", "jest", "--coverage"]
        assert result.value["runner"] == "jest"
        assert result.value["passed"] == 7
        assert result.value["failed"] == 0
        assert result.value["total"] == 7

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_omits_coverage_flag_when_disabled(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(stderr=JEST_PASS_STDERR)

        await runner.run_node_tests(coverage=False)

        assert mock_run.call_args.kwargs["args"] == ["npx", "jest"]

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_yarn_delegates_without_coverage_flag(self, mock_run: AsyncMock) -> None:
        # yarn/npm/pnpm delegate to the project's test script — no --coverage.
        mock_run.return_value = _completed(stderr=JEST_PASS_STDERR)

        await runner.run_node_tests(runner="yarn", args=["--watchAll=false"])

        assert mock_run.call_args.kwargs["args"] == ["yarn", "test", "--watchAll=false"]

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_parses_failed_and_skipped_counts(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(returncode=1, stderr=JEST_FAIL_STDERR)

        result = await runner.run_node_tests()

        assert isinstance(result, SuccessResult)
        assert result.value["returncode"] == 1
        assert result.value["passed"] == 7
        assert result.value["failed"] == 2
        assert result.value["skipped"] == 1
        assert result.value["total"] == 10

    @pytest.mark.asyncio
    async def test_unknown_runner_is_error(self) -> None:
        result = await runner.run_node_tests(runner="mocha")

        assert isinstance(result, ErrorResult)
        assert "Unknown node test runner" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_missing_binary_is_error(self, mock_run: AsyncMock) -> None:
        mock_run.side_effect = FileNotFoundError("npx")

        result = await runner.run_node_tests()

        assert isinstance(result, ErrorResult)
        assert "not found on PATH" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_timeout_is_error(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(returncode=-1, stderr="process timed out")

        result = await runner.run_node_tests(timeout=5)

        assert isinstance(result, ErrorResult)
        assert "timed out" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_nonzero_returncode_is_not_mcp_error(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(returncode=1, stderr=JEST_FAIL_STDERR)

        result = await runner.run_node_tests()

        assert isinstance(result, SuccessResult)
        assert result.value["returncode"] == 1
