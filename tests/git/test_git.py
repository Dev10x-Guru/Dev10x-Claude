from __future__ import annotations

import subprocess
from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest

from dev10x.domain.common.result import ErrorResult, SuccessResult
from dev10x.git import mass_rewrite, push_safe, rebase_groom


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
    @pytest.fixture(autouse=True)
    def _no_remote_base(self) -> Iterator[AsyncMock]:
        # By default the remote-tracking ref does not resolve, so
        # _resolve_groom_base passes the bare base through unchanged and
        # makes no real git calls (GH-486).
        with patch("dev10x.git.async_run", new_callable=AsyncMock) as mock:
            mock.return_value = _completed(returncode=1)
            yield mock

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


class TestPushSafeStructuredOutput:
    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    async def test_parses_structured_success_payload(
        self,
        mock_run_script: AsyncMock,
    ) -> None:
        payload = (
            '{"pushed":true,"ref":"feature","remote":"origin",'
            '"sha":"abc1234","tracking":"origin/feature","ci_run_url":null}'
        )
        mock_run_script.return_value = _completed(stdout=payload)

        result = await push_safe(args=["origin", "feature"])

        assert isinstance(result, SuccessResult)
        assert result.value["pushed"] is True
        assert result.value["ref"] == "feature"
        assert result.value["remote"] == "origin"
        assert result.value["sha"] == "abc1234"
        assert result.value["tracking"] == "origin/feature"
        assert result.value["ci_run_url"] is None

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    async def test_returns_error_on_blocked_force_push(
        self,
        mock_run_script: AsyncMock,
    ) -> None:
        mock_run_script.return_value = _completed(
            returncode=2,
            stderr="BLOCKED: --force push to protected branch 'main' is not allowed.",
        )

        result = await push_safe(args=["origin", "main", "--force"])

        assert isinstance(result, ErrorResult)
        assert "BLOCKED" in result.error


class TestQualifyBaseRef:
    """GH-486: prefer origin/<base> over a possibly-stale local branch."""

    def test_bare_branch_qualified_when_remote_exists(self) -> None:
        from dev10x.git import qualify_base_ref

        assert qualify_base_ref("develop", remote_exists=True) == "origin/develop"

    def test_bare_branch_unchanged_when_no_remote(self) -> None:
        from dev10x.git import qualify_base_ref

        assert qualify_base_ref("develop", remote_exists=True) == "origin/develop"
        assert qualify_base_ref("feature-x", remote_exists=False) == "feature-x"

    def test_already_qualified_ref_passes_through(self) -> None:
        from dev10x.git import qualify_base_ref

        assert qualify_base_ref("origin/develop", remote_exists=True) == "origin/develop"

    def test_sha_like_ref_passes_through(self) -> None:
        from dev10x.git import qualify_base_ref

        # A path-ish / slash-bearing ref is treated as already-qualified.
        assert qualify_base_ref("refs/heads/develop", remote_exists=True) == "refs/heads/develop"


class TestResolveGroomBase:
    """GH-486: resolve effective base ref + stale-local notice."""

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run", new_callable=AsyncMock)
    async def test_local_behind_origin_resolves_to_origin_with_notice(
        self, mock_run: AsyncMock
    ) -> None:
        from dev10x.git import _resolve_groom_base

        # show-ref succeeds (remote exists), rev-list reports 3 commits behind.
        mock_run.side_effect = [
            _completed(returncode=0),
            _completed(returncode=0, stdout="3\n"),
        ]
        effective, notice = await _resolve_groom_base("develop")

        assert effective == "origin/develop"
        assert notice is not None
        assert "3 commit(s) behind origin/develop" in notice

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run", new_callable=AsyncMock)
    async def test_local_up_to_date_no_notice(self, mock_run: AsyncMock) -> None:
        from dev10x.git import _resolve_groom_base

        mock_run.side_effect = [
            _completed(returncode=0),
            _completed(returncode=0, stdout="0\n"),
        ]
        effective, notice = await _resolve_groom_base("develop")

        assert effective == "origin/develop"
        assert notice is None

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run", new_callable=AsyncMock)
    async def test_no_remote_tracking_ref_uses_local(self, mock_run: AsyncMock) -> None:
        from dev10x.git import _resolve_groom_base

        mock_run.return_value = _completed(returncode=1)
        effective, notice = await _resolve_groom_base("develop")

        assert effective == "develop"
        assert notice is None

    @pytest.mark.asyncio
    async def test_already_qualified_ref_skips_git(self) -> None:
        from dev10x.git import _resolve_groom_base

        # No patch needed: a slash-bearing ref returns immediately.
        effective, notice = await _resolve_groom_base("origin/main")

        assert effective == "origin/main"
        assert notice is None

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    @patch("dev10x.git.async_run", new_callable=AsyncMock)
    async def test_rebase_groom_attaches_base_notice(
        self, mock_run: AsyncMock, mock_script: AsyncMock
    ) -> None:
        mock_run.side_effect = [
            _completed(returncode=0),
            _completed(returncode=0, stdout="2\n"),
        ]
        mock_script.return_value = _completed(stdout="commits_rewritten=2")

        result = await rebase_groom(seq_path="/tmp/seq.txt", base_ref="develop")

        assert isinstance(result, SuccessResult)
        assert "base_notice" in result.value
        # The script is invoked with the origin-qualified ref.
        assert mock_script.call_args.args[2] == "origin/develop"
