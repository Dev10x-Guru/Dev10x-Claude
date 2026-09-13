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


XPASS_STDOUT = (
    "============================= test session starts =============================\n"
    "collected 9556 items\n"
    "============ 9543 passed, 13 skipped, 1 xpassed in 294.74s (0:04:54) ============\n"
)

# Observed verbatim while fixing GH-1285: the wrapper scored its own
# passing run as `passed: 0` because `deselected` and `warnings` were
# outside the closed outcome set.
DESELECTED_STDOUT = "===== 19 passed, 104 deselected, 9124 warnings in 0.95s =====\n"

QUIET_STDOUT = "9543 passed, 13 skipped in 294.74s\n"

NO_SUMMARY_STDOUT = (
    "============================= test session starts =============================\n"
    "collected 0 items\n"
)


class TestSummaryParsing:
    """GH-1285: the counts must describe the run, or say they don't."""

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_outcome_outside_the_known_set_does_not_zero_the_counts(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout=XPASS_STDOUT)

        result = await runner.run_tests()

        assert isinstance(result, SuccessResult)
        payload = result.value
        assert payload["summary_parsed"] is True
        assert payload["passed"] == 9543
        assert payload["skipped"] == 13
        assert payload["failed"] == 0

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_deselected_and_warnings_do_not_zero_the_counts(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout=DESELECTED_STDOUT)

        result = await runner.run_tests()

        assert isinstance(result, SuccessResult)
        assert result.value["passed"] == 19
        assert result.value["summary_parsed"] is True

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_quiet_mode_summary_is_parsed(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout=QUIET_STDOUT)

        result = await runner.run_tests()

        assert isinstance(result, SuccessResult)
        payload = result.value
        assert payload["summary_parsed"] is True
        assert payload["passed"] == 9543
        assert payload["skipped"] == 13

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_absent_summary_is_distinguishable_from_an_empty_run(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout=NO_SUMMARY_STDOUT)

        result = await runner.run_tests()

        assert isinstance(result, SuccessResult)
        payload = result.value
        assert payload["summary_parsed"] is False
        assert payload["passed"] == 0

    @pytest.mark.asyncio
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_xpassed_is_not_counted_as_passed(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="==== 1 xpassed in 0.10s ====\n")

        result = await runner.run_tests()

        assert isinstance(result, SuccessResult)
        assert result.value["passed"] == 0
        assert result.value["summary_parsed"] is True


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
        # GH-1198: this repo declares its test deps under the `dev` extra, so
        # the resolved command carries it. Asserting the bare three-token
        # prefix would pin the shape that cannot run this suite.
        assert called_args[:2] == ["uv", "run"]
        assert "pytest" in called_args
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
        assert payload["summary_parsed"] is True

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


MISSING_DEP_STDOUT = (
    "============================= test session starts =============================\n"
    "ImportError while loading conftest 'tests/conftest.py'.\n"
    "ModuleNotFoundError: No module named 'factory'\n"
)


def _write_pyproject(*, tmp_path, extras: str) -> str:
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "demo"\nversion = "0"\n\n[project.optional-dependencies]\n{extras}\n',
        encoding="utf-8",
    )
    return str(tmp_path)


class TestResolveTestExtras:
    """GH-1198: the wrapper resolves the extra that carries the test deps."""

    def test_group_declaring_pytest_is_selected(self, tmp_path) -> None:
        cwd = _write_pyproject(tmp_path=tmp_path, extras='dev = ["pytest>=8.0,<9"]')

        assert runner.resolve_test_extras(cwd=cwd) == ["dev"]

    def test_group_without_pytest_is_not_selected(self, tmp_path) -> None:
        cwd = _write_pyproject(tmp_path=tmp_path, extras='docs = ["mkdocs>=1,<2"]')

        assert runner.resolve_test_extras(cwd=cwd) == []

    def test_narrower_test_group_wins_over_dev(self, tmp_path) -> None:
        cwd = _write_pyproject(
            tmp_path=tmp_path,
            extras='dev = ["pytest>=8,<9"]\ntest = ["pytest>=8,<9"]',
        )

        assert runner.resolve_test_extras(cwd=cwd) == ["test"]

    def test_pytest_plugin_alone_qualifies_the_group(self, tmp_path) -> None:
        cwd = _write_pyproject(tmp_path=tmp_path, extras='qa = ["pytest-cov>=6,<7"]')

        assert runner.resolve_test_extras(cwd=cwd) == ["qa"]

    def test_missing_pyproject_resolves_to_no_extras(self, tmp_path) -> None:
        assert runner.resolve_test_extras(cwd=str(tmp_path)) == []

    def test_unparseable_pyproject_resolves_to_no_extras(self, tmp_path) -> None:
        (tmp_path / "pyproject.toml").write_text("not = [valid", encoding="utf-8")

        assert runner.resolve_test_extras(cwd=str(tmp_path)) == []

    def test_non_table_optional_dependencies_resolves_to_no_extras(self, tmp_path) -> None:
        # Valid TOML, wrong shape. Falling through to a bare `uv run pytest`
        # beats raising out of a wrapper whose whole job is running tests.
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "demo"\nversion = "0"\noptional-dependencies = "dev"\n',
            encoding="utf-8",
        )

        assert runner.resolve_test_extras(cwd=str(tmp_path)) == []

    def test_this_repo_resolves_to_the_dev_extra(self) -> None:
        # The concrete case from the issue: a bare `uv run pytest` dies at
        # collection on `ModuleNotFoundError: No module named 'factory'`.
        assert runner.resolve_test_extras() == ["dev"]


class TestMissingDependencyRetry:
    """The safety net for a project whose extras resolution finds nothing."""

    @pytest.mark.asyncio
    @patch("dev10x.runner.resolve_test_extras", return_value=[])
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_collection_import_error_retries_with_dev_extra(
        self,
        mock_run: AsyncMock,
        _resolve: object,
    ) -> None:
        mock_run.side_effect = [
            _completed(returncode=2, stdout=MISSING_DEP_STDOUT),
            _completed(stdout=PASS_STDOUT),
        ]

        result = await runner.run_tests()

        assert isinstance(result, SuccessResult)
        assert result.value["retried_with_extras"] is True
        assert result.value["extras"] == ["dev"]
        assert mock_run.await_count == 2
        assert ["--extra", "dev"] == mock_run.await_args.kwargs["args"][2:4]

    @pytest.mark.asyncio
    @patch("dev10x.runner.resolve_test_extras", return_value=[])
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_ordinary_failure_is_not_retried(
        self,
        mock_run: AsyncMock,
        _resolve: object,
    ) -> None:
        mock_run.return_value = _completed(returncode=1, stdout=FAIL_STDOUT)

        result = await runner.run_tests()

        assert isinstance(result, SuccessResult)
        assert result.value["retried_with_extras"] is False
        assert mock_run.await_count == 1

    @pytest.mark.asyncio
    @patch("dev10x.runner.resolve_test_extras", return_value=[])
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_passing_run_mentioning_the_error_is_not_retried(
        self,
        mock_run: AsyncMock,
        _resolve: object,
    ) -> None:
        # A test that asserts on ModuleNotFoundError handling puts the string
        # in stdout while passing. Retrying on the text alone would re-run the
        # whole green suite for nothing.
        mock_run.return_value = _completed(returncode=0, stdout=PASS_STDOUT + MISSING_DEP_STDOUT)

        result = await runner.run_tests()

        assert isinstance(result, SuccessResult)
        assert result.value["retried_with_extras"] is False
        assert mock_run.await_count == 1

    @pytest.mark.asyncio
    @patch("dev10x.runner.resolve_test_extras", return_value=["dev"])
    @patch("dev10x.runner.async_run", new_callable=AsyncMock)
    async def test_resolved_extras_skip_the_retry(
        self,
        mock_run: AsyncMock,
        _resolve: object,
    ) -> None:
        # Resolution already applied the extra, so a still-missing module is a
        # genuine project problem — retrying the same command would only hide
        # it behind a second identical failure.
        mock_run.return_value = _completed(returncode=2, stdout=MISSING_DEP_STDOUT)

        result = await runner.run_tests()

        assert isinstance(result, SuccessResult)
        assert result.value["retried_with_extras"] is False
        assert mock_run.await_count == 1
