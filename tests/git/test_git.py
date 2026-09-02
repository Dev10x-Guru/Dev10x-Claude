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

PAUSED_STDOUT = (
    "REBASE_PAUSED\n"
    "conflicted_files=\n"
    "rebase_head=abc1234\n"
    "hint=Rebase stopped with no unmerged paths — inspect git status, "
    "then git rebase --continue (or --abort)"
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

    @pytest.fixture()
    def paused_result(self) -> subprocess.CompletedProcess[str]:
        return _completed(returncode=1, stdout=PAUSED_STDOUT)

    @pytest.mark.asyncio
    @patch("dev10x.git.async_run_script", new_callable=AsyncMock)
    async def test_paused_rebase_is_not_reported_as_a_conflict(
        self,
        mock_run_script: AsyncMock,
        paused_result: subprocess.CompletedProcess[str],
    ) -> None:
        # GH-1103: a rebase that stopped with no unmerged paths used to
        # surface as conflict=True with an empty file list, sending the
        # caller to resolve conflicts git never reported.
        mock_run_script.return_value = paused_result

        result = await rebase_groom(seq_path="/tmp/seq.txt", base_ref="develop")

        assert isinstance(result, ErrorResult)
        assert result.details["conflict"] is False
        assert result.details["paused"] is True
        assert result.details["conflicted_files"] == []
        assert result.details["rebase_head"] == "abc1234"
        assert "no unmerged paths" in result.error


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

    def test_hook_layer_protected_set_matches_the_script_default(self) -> None:
        """GH-1041: the fourth list — the hook redirect guard — is pinned too.

        ``PROTECTED_BRANCHES`` gates ``skill_redirect``'s direct-push escape
        hatch, so a name missing here lets a push through that the push guard
        would have protected. It omitted ``staging`` until GH-1041.
        """
        from dev10x.domain.common.branch_name import PROTECTED_BRANCHES

        assert PROTECTED_BRANCHES == frozenset(self._script_defaults())

    def test_base_branch_priority_stays_narrower_than_protection(self) -> None:
        """The two lists answer different questions and may legitimately differ.

        ``BASE_BRANCH_PRIORITY`` answers "what does a PR target?" — ``staging``
        is never a PR base. Protection is a superset, not an alias; pinning the
        relationship keeps a future edit from collapsing them back together.
        """
        from dev10x.domain.common.branch_name import BASE_BRANCH_PRIORITY, PROTECTED_BRANCHES

        assert frozenset(BASE_BRANCH_PRIORITY) < PROTECTED_BRANCHES
        assert "staging" not in BASE_BRANCH_PRIORITY


class ShellTwinHarness:
    """Fixture and runner shared by the ``git-push-safe.sh`` suites.

    Deliberately not named ``Test*`` so pytest collects it as a base only —
    inheriting one suite from the other would re-run its cases under the
    subclass's name.
    """

    SCRIPT = Path(__file__).parents[2] / "skills" / "git" / "scripts" / "git-push-safe.sh"

    @pytest.fixture
    def repo_on_protected_branch(self, tmp_path: Path) -> Path:
        """A repo whose checked-out branch is protected, with HEAD born.

        The commit is required: on an unborn HEAD the script's
        ``git rev-parse --abbrev-ref HEAD`` fallback yields an empty branch
        name, which is not protected, and every case would reach the push.
        """
        subprocess.run(
            ["git", "init", "-q", "-b", "main", str(tmp_path)],
            check=True,
            timeout=30,
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=test",
                "-c",
                "user.email=test@example.com",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                "root",
            ],
            check=True,
            cwd=tmp_path,
            timeout=30,
        )
        return tmp_path

    def _blocked_reason(self, *args: str, cwd: Path) -> str | None:
        result = subprocess.run(
            [str(self.SCRIPT), *args],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=30,
        )
        match = re.search(r'"blocked_reason":"(?P<reason>[^"]*)"', result.stdout)
        return match.group("reason") if match else None


class TestShellTwinDetectsBundledForceFlags(ShellTwinHarness):
    """GH-1047: the shell twin must agree with the validator on what is force.

    ``skill_redirect._has_bare_force`` and ``git-push-safe.sh`` implement the
    same flag test in two languages, and `.claude/rules/hook-patterns.md`
    requires the pair to stay functionally equivalent. Fixing only the
    validator would leave ``push_safe`` — the very tool force pushes are
    routed into — waving ``-uf origin main`` straight through.

    These run the script directly, with no positional arguments, so the
    target resolves through the ``HEAD`` fallback to the checked-out branch.
    That keeps each case a test of the force check alone; the refspec-parsing
    cases live in the sibling suite below.

    A force push to a protected branch is refused before any ``git push``
    runs, so nothing here needs a remote.
    """

    @pytest.mark.parametrize(
        "flag",
        ["-uf", "-fu", "-vuf", "-f", "--force"],
    )
    def test_force_on_protected_branch_is_blocked(
        self,
        flag: str,
        repo_on_protected_branch: Path,
    ) -> None:
        reason = self._blocked_reason(flag, cwd=repo_on_protected_branch)
        assert reason == "protected_branch_force_push"


class TestShellTwinResolvesExplicitRefspecTargets(ShellTwinHarness):
    """GH-1049: the shell twin must resolve the target it is GIVEN.

    These cases pass positionals rather than relying on the HEAD fallback —
    the fallback is exactly what the gap-1 misparse silently reached.

    The fixture repo is checked out on ``main``, so a case that asserts a
    block must name a protected branch that the HEAD fallback would ALSO
    have produced to be meaningful. `feature_repo` therefore puts HEAD on
    an unprotected branch: with HEAD unprotected, a block can only come
    from the guard actually reading the refspec.
    """

    @pytest.fixture
    def feature_repo(self, repo_on_protected_branch: Path) -> Path:
        """The same repo, moved onto an unprotected branch."""
        subprocess.run(
            ["git", "checkout", "-q", "-b", "feature"],
            check=True,
            cwd=repo_on_protected_branch,
            timeout=30,
        )
        return repo_on_protected_branch

    @pytest.mark.parametrize(
        "args",
        [
            ("--force", "origin", "main"),
            ("-f", "origin", "develop"),
            ("-uf", "origin", "master"),
        ],
    )
    def test_explicit_protected_target_is_blocked_from_any_branch(
        self,
        args: tuple[str, ...],
        feature_repo: Path,
    ) -> None:
        """Gap 1: the loop overwrote ``remote`` with BOTH positionals when
        the remote was actually named ``origin``, so ``target_branch`` was
        never set and fell back to the current branch. A force push to
        ``main`` was not blocked on its canonical spelling."""
        assert self._blocked_reason(*args, cwd=feature_repo) == "protected_branch_force_push"

    def test_reported_ref_is_the_branch_not_the_remote(self, feature_repo: Path) -> None:
        """The same misparse was visible in the payload, which reported the
        branch name under ``remote``."""
        result = subprocess.run(
            [str(self.SCRIPT), "--force", "origin", "main"],
            capture_output=True,
            text=True,
            cwd=feature_repo,
            timeout=30,
        )
        assert '"ref":"main"' in result.stdout
        assert '"remote":"origin"' in result.stdout

    def test_value_taking_flag_value_is_not_read_as_a_positional(
        self,
        feature_repo: Path,
    ) -> None:
        """Gap 2: ``ci.skip`` is not a ``-``-prefixed token, so it entered
        the positional stream and shifted the refspec out of reach."""
        reason = self._blocked_reason(
            "-o", "ci.skip", "--force", "origin", "main", cwd=feature_repo
        )
        assert reason == "protected_branch_force_push"

    @pytest.mark.parametrize(
        "args",
        [
            ("origin", "+evil:main"),
            ("origin", "+main"),
            ("origin", "feature", "+evil:develop"),
        ],
    )
    def test_plus_prefixed_refspec_counts_as_force(
        self,
        args: tuple[str, ...],
        feature_repo: Path,
    ) -> None:
        """Gap 3: refspec syntax force-pushes with no force flag, and only
        the first refspec was inspected."""
        assert self._blocked_reason(*args, cwd=feature_repo) == "protected_branch_force_push"

    def test_fully_qualified_ref_is_recognised_as_protected(self, feature_repo: Path) -> None:
        """Gap 4: ``PROTECTED_BRANCHES`` holds short names."""
        reason = self._blocked_reason("origin", "+feature:refs/heads/main", cwd=feature_repo)
        assert reason == "protected_branch_force_push"

    @pytest.mark.parametrize(
        "args",
        [
            ("--force", "origin", "feature"),
            ("--force-with-lease", "origin", "main"),
            ("-o", "ci.skip", "--force", "origin", "feature"),
        ],
    )
    def test_permitted_pushes_are_not_blocked_as_protected(
        self,
        args: tuple[str, ...],
        feature_repo: Path,
    ) -> None:
        """The tightening must not over-block: a force push to an
        unprotected branch is allowed, and ``--force-with-lease`` is
        allowed even against a protected branch. Neither has a remote to
        reach, so each fails at the push itself — ``push_failed`` proves
        the guard let it through."""
        assert self._blocked_reason(*args, cwd=feature_repo) == "push_failed"

    @pytest.mark.parametrize(
        "flag",
        ["-u", "-vu", "--force-with-lease"],
    )
    def test_non_force_flags_reach_the_push(
        self,
        flag: str,
        repo_on_protected_branch: Path,
    ) -> None:
        """A non-force flag must get PAST the guard even on a protected branch.

        ``push_failed`` is the discriminator: it is only reachable after the
        force check declined to fire, so it proves the cluster decomposition
        introduced no false positive. The push itself fails because the repo
        has no remote, which is why this needs no network.
        """
        reason = self._blocked_reason(flag, cwd=repo_on_protected_branch)
        assert reason == "push_failed"


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
