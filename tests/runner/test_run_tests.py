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


PASS_STDOUT = (
    "============================= test session starts =============================\n"
    "collected 150 items\n"
    "tests/test_foo.py::test_bar PASSED\n"
    "---------- coverage: platform linux, python 3.12.0 -----------\n"
    "Name                  Stmts   Miss  Cover   Missing\n"
    "---------------------------------------------------\n"
    "src/dev10x/foo.py        20      0   100%\n"
    "---------------------------------------------------\n"
    "TOTAL                    20      0   100%\n"
    "============================= 150 passed in 2.34s =============================\n"
)

FAIL_STDOUT = (
    "============================= test session starts =============================\n"
    "FAILED tests/test_foo.py::test_bar - AssertionError: expected 1, got 2\n"
    "FAILED tests/test_baz.py::test_qux\n"
    "---------- coverage: platform linux, python 3.12.0 -----------\n"
    "Name                  Stmts   Miss  Cover   Missing\n"
    "---------------------------------------------------\n"
    "src/dev10x/foo.py        20      2    90%   12-13\n"
    "---------------------------------------------------\n"
    "TOTAL                    20      2    90%\n"
    "===================== 148 passed, 2 failed in 3.21s ======================\n"
)


class TestRunTests:
    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_invokes_uv_run_pytest_with_coverage_by_default(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout=PASS_STDOUT)

        result = await runner.run_tests()

        assert isinstance(result, SuccessResult)
        called_args = mock_run.call_args.kwargs["args"]
        assert called_args[:3] == ["uv", "run", "pytest"]
        assert "--cov" in called_args
        assert "--cov-report=term-missing" in called_args
        assert "--tb=short" in called_args
        assert "--color=no" in called_args

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_appends_extra_args_after_coverage_flags(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout=PASS_STDOUT)

        await runner.run_tests(args=["-k", "test_foo", "src/dev10x/runner/"])

        called_args = mock_run.call_args.kwargs["args"]
        assert called_args[-3:] == ["-k", "test_foo", "src/dev10x/runner/"]

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_omits_coverage_flags_when_disabled(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout=PASS_STDOUT)

        await runner.run_tests(coverage=False)

        called_args = mock_run.call_args.kwargs["args"]
        assert "--cov" not in called_args
        assert "--cov-report=term-missing" not in called_args

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_parses_passing_summary_and_coverage(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout=PASS_STDOUT)

        result = await runner.run_tests()

        assert isinstance(result, SuccessResult)
        payload = result.value
        assert payload["returncode"] == 0
        assert payload["passed"] == 150
        assert payload["failed"] == 0
        assert payload["coverage_percent"] == 100
        assert payload["failed_tests"] == []
        assert payload["missing_coverage"] == []
        assert payload["summary"].startswith("150 passed")

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_parses_failed_tests_and_missing_coverage(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stdout=FAIL_STDOUT)

        result = await runner.run_tests()

        assert isinstance(result, SuccessResult)
        payload = result.value
        assert payload["returncode"] == 1
        assert payload["passed"] == 148
        assert payload["failed"] == 2
        assert payload["coverage_percent"] == 90
        assert {f["id"] for f in payload["failed_tests"]} == {
            "tests/test_foo.py::test_bar",
            "tests/test_baz.py::test_qux",
        }
        first = next(
            f for f in payload["failed_tests"] if f["id"] == "tests/test_foo.py::test_bar"
        )
        assert first["message"] == "AssertionError: expected 1, got 2"
        assert payload["missing_coverage"] == [
            {"file": "src/dev10x/foo.py", "percent": 90, "lines": "12-13"},
        ]

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_nonzero_returncode_is_not_an_mcp_error(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stdout=FAIL_STDOUT)

        result = await runner.run_tests()

        assert isinstance(result, SuccessResult)

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_timeout_returns_error(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(
            returncode=-1,
            stderr="Process timed out",
        )

        result = await runner.run_tests(timeout=5)

        assert isinstance(result, ErrorResult)
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_missing_uv_returns_error(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.side_effect = FileNotFoundError("uv")

        result = await runner.run_tests()

        assert isinstance(result, ErrorResult)
        assert "uv" in result.error
