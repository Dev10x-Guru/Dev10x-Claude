from __future__ import annotations

import re
import subprocess
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dev10x.domain.common.result import ErrorResult, SuccessResult
from dev10x.git import (
    create_worktree,
    mass_rewrite,
    next_worktree_name,
    push_safe,
    rebase_groom,
)


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


class TestPushSafeProtectedBranchResolution:
    """GH-1031: the protected set resolves without the caller supplying it.

    Previously an omitted ``protected_branches`` sent no ``--protected``
    flags at all, so the only protection was whatever
    ``git-push-safe.sh`` hardcoded — a project with a differently-named
    integration branch had to pass the list on every call, which an
    unattended agent never does.
    """

    @staticmethod
    def _protected_flags(mock_run_script: AsyncMock) -> list[str]:
        args = list(mock_run_script.call_args.args)
        return [args[i + 1] for i, arg in enumerate(args) if arg == "--protected"]

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    @patch("dev10x.git.SessionYamlDocument")
    @patch("dev10x.git.GitContext")
    async def test_explicit_list_wins_over_the_durable_pref(
        self,
        mock_ctx: MagicMock,
        mock_doc: MagicMock,
        mock_run_script: AsyncMock,
    ) -> None:
        mock_run_script.return_value = _completed(stdout='{"pushed":true}')
        mock_doc.return_value.read_protected_branches.return_value = ["trunk"]

        await push_safe(args=["origin", "feature"], protected_branches=["main", "release/*"])

        assert self._protected_flags(mock_run_script) == ["main", "release/*"]
        # An explicit list short-circuits before the pref is consulted, so
        # resolving the repo root at all would be wasted work.
        mock_ctx.assert_not_called()

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    @patch("dev10x.git.SessionYamlDocument")
    @patch("dev10x.git.GitContext")
    async def test_durable_pref_applies_when_caller_passes_nothing(
        self,
        mock_ctx: object,
        mock_doc: object,
        mock_run_script: AsyncMock,
    ) -> None:
        mock_run_script.return_value = _completed(stdout='{"pushed":true}')
        mock_ctx.return_value.toplevel = "/repo"
        mock_doc.return_value.read_protected_branches.return_value = ["trunk", "release/*"]

        await push_safe(args=["origin", "feature"])

        assert self._protected_flags(mock_run_script) == ["trunk", "release/*"]

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    @patch("dev10x.git.SessionYamlDocument")
    @patch("dev10x.git.GitContext")
    async def test_no_pref_sends_no_flags_so_the_script_default_applies(
        self,
        mock_ctx: object,
        mock_doc: object,
        mock_run_script: AsyncMock,
    ) -> None:
        mock_run_script.return_value = _completed(stdout='{"pushed":true}')
        mock_ctx.return_value.toplevel = "/repo"
        mock_doc.return_value.read_protected_branches.return_value = None

        await push_safe(args=["origin", "feature"])

        assert self._protected_flags(mock_run_script) == []

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    @patch("dev10x.git.GitContext")
    async def test_unresolvable_repo_root_sends_no_flags(
        self,
        mock_ctx: object,
        mock_run_script: AsyncMock,
    ) -> None:
        """Degrade to the script's wider default, never to zero protection."""
        mock_run_script.return_value = _completed(stdout='{"pushed":true}')
        mock_ctx.return_value.toplevel = None

        await push_safe(args=["origin", "feature"])

        assert self._protected_flags(mock_run_script) == []


class TestProtectedBranchDefaultIsDocumentedAccurately:
    """GH-1031's root cause: two disagreeing statements of one default.

    ``push_safe``'s docstring claimed "main, develop" while the shell script
    actually protected six branches. That drift is what produced a bug
    report asking for a widening that had already shipped — so the docstring
    is pinned to the script rather than restated by hand.
    """

    SCRIPT = Path(__file__).parents[2] / "skills" / "git" / "scripts" / "protected-branches.sh"

    def _script_defaults(self) -> list[str]:
        match = re.search(
            r"^DEFAULT_PROTECTED_BRANCHES=\((?P<branches>[^)]*)\)",
            self.SCRIPT.read_text(),
            re.MULTILINE,
        )
        assert match is not None, "DEFAULT_PROTECTED_BRANCHES not found in the shell script"
        return match.group("branches").split()

    def test_script_default_is_wider_than_main_and_develop(self) -> None:
        """The premise of the original report — kept as a live assertion."""
        assert {"master", "development"} <= set(self._script_defaults())

    def test_mcp_docstring_lists_the_script_default_verbatim(self) -> None:
        source = Path(__file__).parents[2] / "src" / "dev10x" / "mcp" / "git_tools.py"
        collapsed = " ".join(source.read_text().split())
        assert " ".join(self._script_defaults()) in collapsed


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

        # Single rev-list call reports 3 commits behind (both refs exist).
        mock_run.return_value = _completed(returncode=0, stdout="3\n")
        effective, notice = await _resolve_groom_base("develop")

        assert effective == "origin/develop"
        assert notice is not None
        assert "3 commit(s) behind origin/develop" in notice
        assert mock_run.await_count == 1

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run", new_callable=AsyncMock)
    async def test_local_up_to_date_no_notice(self, mock_run: AsyncMock) -> None:
        from dev10x.git import _resolve_groom_base

        mock_run.return_value = _completed(returncode=0, stdout="0\n")
        effective, notice = await _resolve_groom_base("develop")

        assert effective == "origin/develop"
        assert notice is None

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run", new_callable=AsyncMock)
    async def test_no_remote_tracking_ref_uses_local(self, mock_run: AsyncMock) -> None:
        from dev10x.git import _resolve_groom_base

        # rev-list exits non-zero when either ref is absent → local base.
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
        mock_run.return_value = _completed(returncode=0, stdout="2\n")
        mock_script.return_value = _completed(stdout="commits_rewritten=2")

        result = await rebase_groom(seq_path="/tmp/seq.txt", base_ref="develop")

        assert isinstance(result, SuccessResult)
        assert "base_notice" in result.value
        # The script is invoked with the origin-qualified ref.
        assert mock_script.call_args.args[2] == "origin/develop"


class TestCreateWorktreeArgumentMapping:
    """GH-960: create_worktree must not misroute base/path into the
    script's positional repo-root slot."""

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    async def test_forwards_explicit_path_and_base_positionally(
        self,
        mock_run_script: AsyncMock,
    ) -> None:
        mock_run_script.return_value = _completed(
            stdout='{"worktree_path": "/tmp/wt", "branch": "feat", "created": true}'
        )

        result = await create_worktree(
            branch="janusz/GH-1/slug",
            base="origin/develop",
            path="/tmp/wt",
        )

        assert isinstance(result, SuccessResult)
        # No lookup of a default path — async_run_script is called exactly
        # once, directly for create-worktree.sh (not preceded by a
        # next-worktree-name.sh call).
        assert mock_run_script.await_count == 1
        args = mock_run_script.call_args.args
        assert args[0] == "skills/git-worktree/scripts/create-worktree.sh"
        assert args[1] == "/tmp/wt"
        assert args[2] == "janusz/GH-1/slug"
        assert args[3] == "origin/develop"

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    async def test_defaults_path_via_next_worktree_name_when_omitted(
        self,
        mock_run_script: AsyncMock,
    ) -> None:
        mock_run_script.side_effect = [
            _completed(stdout="/work/proj/.worktrees/proj-3"),
            _completed(stdout='{"worktree_path": "/work/proj/.worktrees/proj-3"}'),
        ]

        result = await create_worktree(branch="janusz/GH-1/slug")

        assert isinstance(result, SuccessResult)
        assert mock_run_script.await_count == 2

        first_call_args = mock_run_script.call_args_list[0].args
        assert first_call_args[0] == "skills/git-worktree/scripts/next-worktree-name.sh"

        second_call_args = mock_run_script.call_args_list[1].args
        assert second_call_args[0] == "skills/git-worktree/scripts/create-worktree.sh"
        assert second_call_args[1] == "/work/proj/.worktrees/proj-3"
        assert second_call_args[2] == "janusz/GH-1/slug"
        assert second_call_args[3] == ""

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    async def test_propagates_next_worktree_name_failure(
        self,
        mock_run_script: AsyncMock,
    ) -> None:
        mock_run_script.return_value = _completed(returncode=1, stderr="no repo found")

        result = await create_worktree(branch="janusz/GH-1/slug")

        assert isinstance(result, ErrorResult)
        assert result.error == "no repo found"
        # Never reaches the create-worktree.sh call.
        assert mock_run_script.await_count == 1

    @pytest.mark.asyncio
    async def test_rejects_protected_branch(self) -> None:
        result = await create_worktree(branch="develop")

        assert isinstance(result, ErrorResult)
        assert "protected" in result.error


class TestNextWorktreeName:
    """GH-960: regression coverage for the wrapper-level tool; the
    parent-resolution fix itself lives in next-worktree-name.sh and is
    exercised end-to-end in tests/skills/git-worktree/."""

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    async def test_returns_path_from_script_stdout(
        self,
        mock_run_script: AsyncMock,
    ) -> None:
        mock_run_script.return_value = _completed(stdout="/work/proj/.worktrees/proj-4")

        result = await next_worktree_name()

        assert isinstance(result, SuccessResult)
        assert result.value["path"] == "/work/proj/.worktrees/proj-4"

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    async def test_forwards_base_dir_override(
        self,
        mock_run_script: AsyncMock,
    ) -> None:
        mock_run_script.return_value = _completed(stdout="/custom/.worktrees/proj-1")

        await next_worktree_name(base_dir="/custom/.worktrees")

        args = mock_run_script.call_args.args
        assert args[0] == "skills/git-worktree/scripts/next-worktree-name.sh"
        assert args[1] == "/custom/.worktrees"
