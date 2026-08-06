from __future__ import annotations

import os
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


class TestNamedPackageScript:
    """GH-1029: ``script=`` brings a non-test check inside the wrapper.

    Without it only the hardcoded ``test`` script was reachable, so a
    ``lint:tsc`` check had to be run as a raw ``node …/tsc`` invocation on
    the Bash layer — outside the wrapper's guardrails and into the
    brace-expansion block no allow-rule can suppress.
    """

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_named_script_uses_the_run_verb(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(stderr=JEST_PASS_STDERR)

        await runner.run_node_tests(runner="npm", script="lint:tsc")

        assert mock_run.call_args.kwargs["args"] == ["npm", "run", "lint:tsc"]

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_default_script_keeps_the_historical_shape(self, mock_run: AsyncMock) -> None:
        """``yarn test``, not ``yarn run test`` — no existing caller changes."""
        mock_run.return_value = _completed(stderr=JEST_PASS_STDERR)

        await runner.run_node_tests(runner="yarn")

        assert mock_run.call_args.kwargs["args"] == ["yarn", "test"]

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_explicit_default_script_is_also_the_historical_shape(
        self, mock_run: AsyncMock
    ) -> None:
        mock_run.return_value = _completed(stderr=JEST_PASS_STDERR)

        await runner.run_node_tests(runner="pnpm", script="test")

        assert mock_run.call_args.kwargs["args"] == ["pnpm", "test"]

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_extra_args_follow_the_named_script(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(stderr=JEST_PASS_STDERR)

        await runner.run_node_tests(runner="yarn", script="lint", args=["--max-warnings=0"])

        assert mock_run.call_args.kwargs["args"] == [
            "yarn",
            "run",
            "lint",
            "--max-warnings=0",
        ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("direct_runner", ["jest", "vitest"])
    async def test_named_script_rejected_for_a_direct_runner(self, direct_runner: str) -> None:
        """Fail loud rather than silently dropping the caller's script."""
        result = await runner.run_node_tests(runner=direct_runner, script="lint:tsc")

        assert isinstance(result, ErrorResult)
        assert "cannot run the package.json script" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_direct_runner_accepts_the_default_script(self, mock_run: AsyncMock) -> None:
        """The guard must not reject the default every jest caller relies on."""
        mock_run.return_value = _completed(stderr=JEST_PASS_STDERR)

        result = await runner.run_node_tests(runner="jest")

        assert isinstance(result, SuccessResult)
        assert mock_run.call_args.kwargs["args"] == ["npx", "jest", "--coverage"]

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_script_is_echoed_in_the_payload(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(stderr=JEST_PASS_STDERR)

        result = await runner.run_node_tests(runner="npm", script="lint:tsc")

        assert isinstance(result, SuccessResult)
        assert result.value["script"] == "lint:tsc"

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_coverage_flag_never_reaches_a_named_script(self, mock_run: AsyncMock) -> None:
        """Coverage only applies to jest/vitest, which reject ``script``."""
        mock_run.return_value = _completed(stderr=JEST_PASS_STDERR)

        await runner.run_node_tests(runner="npm", script="lint:tsc", coverage=True)

        assert "--coverage" not in mock_run.call_args.kwargs["args"]


class TestEnvOverlay:
    """GH-1029: ``env=`` pins what a package script's own definition pins.

    ``create_subprocess_exec(env=...)`` REPLACES the environment, so passing
    the caller's mapping through raw would launch the runner without
    ``PATH``. The overlay keeps the inherited environment and layers on top.
    """

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_no_env_inherits_everything(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(stderr=JEST_PASS_STDERR)

        await runner.run_node_tests()

        assert mock_run.call_args.kwargs["env"] is None

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_empty_env_inherits_everything(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(stderr=JEST_PASS_STDERR)

        await runner.run_node_tests(env={})

        assert mock_run.call_args.kwargs["env"] is None

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_env_overlays_rather_than_replaces(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(stderr=JEST_PASS_STDERR)

        with patch.dict(os.environ, {"PATH": "/usr/bin", "TZ": "UTC"}, clear=True):
            await runner.run_node_tests(env={"TZ": "America/New_York"})

        passed_env = mock_run.call_args.kwargs["env"]
        assert passed_env["TZ"] == "America/New_York"
        assert passed_env["PATH"] == "/usr/bin"
