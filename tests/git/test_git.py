from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock, patch

import pytest

from dev10x.domain.result import ErrorResult, SuccessResult
from dev10x.git import mass_rewrite, rebase_groom


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


CONFLICT_STDOUT = (
    "CONFLICT_DETECTED\n"
    "conflicted_files=src/service.py,src/models.py,\n"
    "rebase_head=abc1234\n"
    "hint=Resolve conflicts, git add, then git rebase --continue"
)


class TestRebaseGroomConflictDetection:
    @pytest.fixture()
    def conflict_result(self) -> subprocess.CompletedProcess[str]:
        return _completed(returncode=1, stdout=CONFLICT_STDOUT)

    @pytest.fixture()
    def non_conflict_failure(self) -> subprocess.CompletedProcess[str]:
        return _completed(returncode=1, stderr="fatal: invalid upstream")

    @pytest.fixture()
    def success_result(self) -> subprocess.CompletedProcess[str]:
        return _completed(stdout="commits_rewritten=3")

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    async def test_returns_conflict_info_on_conflict(
        self,
        mock_run_script: AsyncMock,
        conflict_result: subprocess.CompletedProcess[str],
    ) -> None:
        mock_run_script.return_value = conflict_result

        result = await rebase_groom(seq_path="/tmp/seq.txt", base_ref="develop")

        assert isinstance(result, ErrorResult)
        assert result.details["conflict"] is True
        assert result.details["conflicted_files"] == ["src/service.py", "src/models.py"]
        assert result.details["rebase_head"] == "abc1234"

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    async def test_returns_error_on_non_conflict_failure(
        self,
        mock_run_script: AsyncMock,
        non_conflict_failure: subprocess.CompletedProcess[str],
    ) -> None:
        mock_run_script.return_value = non_conflict_failure

        result = await rebase_groom(seq_path="/tmp/seq.txt", base_ref="develop")

        assert isinstance(result, ErrorResult)
        assert "conflict" not in result.details
        assert result.error == "fatal: invalid upstream"

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    async def test_returns_parsed_output_on_success(
        self,
        mock_run_script: AsyncMock,
        success_result: subprocess.CompletedProcess[str],
    ) -> None:
        mock_run_script.return_value = success_result

        result = await rebase_groom(seq_path="/tmp/seq.txt", base_ref="develop")

        assert isinstance(result, SuccessResult)
        assert result.value["commits_rewritten"] == "3"


class TestMassRewriteConflictDetection:
    @pytest.fixture()
    def conflict_result(self) -> subprocess.CompletedProcess[str]:
        return _completed(
            returncode=1,
            stdout=(
                "Base: develop  |  Commits to rewrite: 2\n"
                "Running rebase…\n"
                "CONFLICT_DETECTED\n"
                "conflicted_files=src/handler.py,\n"
                "rebase_head=def5678\n"
                "hint=Resolve conflicts, git add, then git rebase --continue"
            ),
        )

    @pytest.fixture()
    def non_conflict_failure(self) -> subprocess.CompletedProcess[str]:
        return _completed(
            returncode=1,
            stdout="Base: develop",
            stderr="Rebase failed.",
        )

    @pytest.fixture()
    def success_result(self) -> subprocess.CompletedProcess[str]:
        return _completed(stdout="Done. New log:\nabc1234 Enable feature")

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    async def test_returns_conflict_info_on_conflict(
        self,
        mock_run_script: AsyncMock,
        conflict_result: subprocess.CompletedProcess[str],
    ) -> None:
        mock_run_script.return_value = conflict_result

        result = await mass_rewrite(config_path="/tmp/config.json")

        assert isinstance(result, ErrorResult)
        assert result.details["conflict"] is True
        assert result.details["conflicted_files"] == ["src/handler.py"]
        assert result.details["rebase_head"] == "def5678"

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    async def test_returns_error_on_non_conflict_failure(
        self,
        mock_run_script: AsyncMock,
        non_conflict_failure: subprocess.CompletedProcess[str],
    ) -> None:
        mock_run_script.return_value = non_conflict_failure

        result = await mass_rewrite(config_path="/tmp/config.json")

        assert isinstance(result, ErrorResult)
        assert "conflict" not in result.details
        assert result.error == "Rebase failed."

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    async def test_returns_output_on_success(
        self,
        mock_run_script: AsyncMock,
        success_result: subprocess.CompletedProcess[str],
    ) -> None:
        mock_run_script.return_value = success_result

        result = await mass_rewrite(config_path="/tmp/config.json")

        assert isinstance(result, SuccessResult)
        assert "Enable feature" in result.value["output"]
