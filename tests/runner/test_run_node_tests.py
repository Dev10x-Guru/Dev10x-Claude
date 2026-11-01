from __future__ import annotations

import os
import subprocess
from unittest.mock import AsyncMock, patch

import pytest
from dev10x.domain.common.result import ErrorResult, SuccessResult

from dev10x import runner
from dev10x.subprocess_utils import TimedOutProcess


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

VITEST_PASS_STDOUT = (
    " Test Files  16 passed (16)\n"
    "      Tests  556 passed (556)\n"
    "   Start at  10:00:00\n"
    "   Duration  4.21s\n"
)

VITEST_FAIL_STDOUT = (
    " Test Files  1 failed | 15 passed (16)\n      Tests  2 failed | 554 passed (556)\n"
)

VITEST_COLORED_STDOUT = "\x1b[2m      Tests \x1b[22m \x1b[1m\x1b[32m3 passed\x1b[39m\x1b[22m (3)\n"

JEST_NO_TESTS_STDOUT = "No tests found, exiting with code 1\n"


@pytest.fixture(autouse=True)
def project_root(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(runner, "effective_cwd", lambda: str(tmp_path))
    return tmp_path


class TestSummaryParsing:
    """GH-1285: zero counts must not stand in for an unparsed summary."""

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_a_parsed_summary_says_so(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(stderr=JEST_PASS_STDERR)

        result = await runner.run_node_tests()

        assert isinstance(result, SuccessResult)
        assert result.value["summary_parsed"] is True

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_an_absent_summary_is_distinguishable_from_an_empty_run(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stderr="Time: 0.01 s\n")

        result = await runner.run_node_tests()

        assert isinstance(result, SuccessResult)
        assert result.value["summary_parsed"] is False
        assert result.value["passed"] == 0


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
    async def test_queued_timeout_has_its_own_verdict(self, mock_run: AsyncMock) -> None:
        """GH-1760: the runner never started, so it did not time out."""
        mock_run.return_value = TimedOutProcess(args=[], queued=True)

        result = await runner.run_node_tests(timeout=5)

        assert isinstance(result, ErrorResult)
        assert result.to_dict()["verdict"] == "queue_timeout"

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


class TestRunnerDetection:
    """GH-1683: an omitted runner is detected from the project, not assumed."""

    @pytest.mark.parametrize(
        ("files", "expected"),
        [
            ({}, "jest"),
            ({"vitest.config.mts": ""}, "vitest"),
            ({"vitest.config.ts": "", "jest.config.js": ""}, "vitest"),
            ({"jest.config.cjs": ""}, "jest"),
            ({"package.json": '{"jest": {}}'}, "jest"),
            ({"package.json": '{"scripts": {"test": "x"}}', "pnpm-lock.yaml": ""}, "pnpm"),
            ({"package.json": '{"scripts": {"test": "x"}}', "yarn.lock": ""}, "yarn"),
            ({"package.json": '{"scripts": {"test": "x"}}'}, "npm"),
            ({"package.json": '{"scripts": {"lint": "x"}}'}, "jest"),
            ({"package.json": "not json"}, "jest"),
            ({"package.json": "[]"}, "jest"),
        ],
    )
    def test_detects_runner(self, project_root, files: dict[str, str], expected: str) -> None:
        for name, content in files.items():
            (project_root / name).write_text(content)

        assert runner.detect_node_runner(cwd=str(project_root)) == expected

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_omitted_runner_uses_detected_vitest(
        self,
        mock_run: AsyncMock,
        project_root,
    ) -> None:
        (project_root / "vitest.config.mts").write_text("")
        mock_run.return_value = _completed(stdout=VITEST_PASS_STDOUT)

        result = await runner.run_node_tests(coverage=False)

        assert isinstance(result, SuccessResult)
        assert mock_run.call_args.kwargs["args"] == ["npx", "vitest", "run"]
        assert result.value["runner"] == "vitest"

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_explicit_runner_skips_detection(
        self,
        mock_run: AsyncMock,
        project_root,
    ) -> None:
        (project_root / "vitest.config.mts").write_text("")
        mock_run.return_value = _completed(stderr=JEST_PASS_STDERR)

        result = await runner.run_node_tests(runner="jest", coverage=False)

        assert isinstance(result, SuccessResult)
        assert mock_run.call_args.kwargs["args"] == ["npx", "jest"]


class TestVitestSummary:
    @pytest.mark.parametrize(
        ("stdout", "passed", "failed", "total"),
        [
            (VITEST_PASS_STDOUT, 556, 0, 556),
            (VITEST_FAIL_STDOUT, 554, 2, 556),
            (VITEST_COLORED_STDOUT, 3, 0, 3),
        ],
    )
    def test_parses_vitest_summary(
        self,
        stdout: str,
        passed: int,
        failed: int,
        total: int,
    ) -> None:
        parsed = runner._parse_node(stdout)

        assert parsed["summary_parsed"] is True
        assert (parsed["passed"], parsed["failed"], parsed["total"]) == (passed, failed, total)

    def test_test_files_line_is_not_the_test_count(self) -> None:
        parsed = runner._parse_node(" Test Files  16 passed (16)\n")

        assert parsed["summary_parsed"] is False

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_failing_vitest_run_is_a_result_not_an_error(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(returncode=1, stdout=VITEST_FAIL_STDOUT)

        result = await runner.run_node_tests(runner="vitest")

        assert isinstance(result, SuccessResult)
        assert result.value["failed"] == 2


class TestNoTestsRan:
    """GH-1683: a non-zero exit with nothing executed must not read as clean."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "stderr",
        [JEST_NO_TESTS_STDOUT, "Tests:       0 total\n", "Tests:       nothing\n"],
    )
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_nonzero_exit_without_executed_tests_is_error(
        self,
        mock_run: AsyncMock,
        stderr: str,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stderr=stderr)

        result = await runner.run_node_tests(runner="jest")

        assert isinstance(result, ErrorResult)
        assert "jest exited 1" in result.error
        assert "runner=" in result.error
        assert result.to_dict()["verdict"] == "no_tests_ran"

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_named_script_failure_stays_a_result(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(returncode=2, stderr="error TS2304\n")

        result = await runner.run_node_tests(runner="npm", script="lint:tsc")

        assert isinstance(result, SuccessResult)
        assert result.value["returncode"] == 2

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_zero_exit_without_summary_stays_a_result(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(returncode=0, stderr="")

        result = await runner.run_node_tests(runner="jest")

        assert isinstance(result, SuccessResult)
