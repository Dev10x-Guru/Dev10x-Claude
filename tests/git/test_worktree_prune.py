"""Classifying worktrees for pruning (GH-1930).

The survey runs against real repositories: the field sweep that filed
GH-1930 failed on how git reports squash merges, generated mirrors and
detached checkouts, so a mock of git would only agree with itself. The
two network-facing lookups — gh for PR state, herdr for open workspaces —
are injected stubs.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from dev10x.domain.common.result import ErrorResult, SuccessResult

from dev10x.coding.git import worktree_prune as wp
from dev10x.subprocess_utils import use_cwd
from tests.fakers.process import completed

_TIMEOUT_SECONDS = 30
_COMMIT_DATE = "2026-01-02T03:04:05+02:00"


@pytest.fixture(autouse=True)
def isolated_git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_AUTHOR_DATE", _COMMIT_DATE)
    monkeypatch.setenv("GIT_COMMITTER_DATE", _COMMIT_DATE)


@pytest.fixture(autouse=True)
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv(wp.HERDR_ENV_VAR, raising=False)
    return home


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=True,
        cwd=cwd,
        timeout=_TIMEOUT_SECONDS,
    ).stdout.strip()


def _commit(*, cwd: Path, name: str) -> str:
    (cwd / name).write_text(f"{name}\n")
    _git("add", name, cwd=cwd)
    _git("commit", "-q", "-m", f"add {name}", cwd=cwd)
    return _git("rev-parse", "HEAD", cwd=cwd)


def _add_worktree(*, repo: Path, name: str, branch: str | None) -> Path:
    path = repo.parent / name
    target = ["-b", branch] if branch else ["--detach"]
    _git("worktree", "add", "-q", *target, str(path), "origin/develop", cwd=repo)
    return path


def _pushed_branch(*, repo: Path, name: str, branch: str) -> tuple[Path, str]:
    path = _add_worktree(repo=repo, name=name, branch=branch)
    head = _commit(cwd=path, name=f"{name}.txt")
    _git("push", "-q", "origin", branch, cwd=path)
    return path, head


def _pr(*, number: int, state: str, head_oid: str) -> wp.PullRequestState:
    return wp.PullRequestState(
        known=True,
        latest=wp.PullRequestRef(number=number, state=state, head_oid=head_oid),
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    _git("init", "-q", "--bare", "-b", "develop", str(origin), cwd=tmp_path)
    main = tmp_path / "main"
    _git("clone", "-q", str(origin), str(main), cwd=tmp_path)
    _git("config", "user.name", "test", cwd=main)
    _git("config", "user.email", "test@example.com", cwd=main)
    _git("symbolic-ref", "HEAD", "refs/heads/develop", cwd=main)
    _commit(cwd=main, name="base.txt")
    _git("push", "-q", "-u", "origin", "develop", cwd=main)
    return main


@pytest.fixture
def worktrees(repo: Path) -> dict[str, Any]:
    squash, squash_head = _pushed_branch(repo=repo, name="wt-squash", branch="feat/squash")
    closed, closed_head = _pushed_branch(repo=repo, name="wt-closed", branch="feat/closed")
    mirrors, mirrors_head = _pushed_branch(repo=repo, name="wt-mirrors", branch="feat/mirrors")
    (mirrors / ".agents").mkdir()
    (mirrors / ".agents" / "skill.md").write_text("generated\n")
    (mirrors / ".codex").mkdir()
    (mirrors / ".codex" / "agent.md").write_text("generated\n")
    in_use, in_use_head = _pushed_branch(repo=repo, name="wt-open", branch="feat/open")
    dirty, dirty_head = _pushed_branch(repo=repo, name="wt-dirty", branch="feat/dirty")
    (dirty / "wt-dirty.txt").write_text("edited\n")
    (dirty / ".agents").mkdir()
    (dirty / ".agents" / "skill.md").write_text("generated\n")
    moved, _ = _pushed_branch(repo=repo, name="wt-moved", branch="feat/moved")
    _commit(cwd=moved, name="after-merge.txt")
    _git("push", "-q", "origin", "feat/moved", cwd=moved)
    open_pr, open_head = _pushed_branch(repo=repo, name="wt-open-pr", branch="feat/open-pr")
    unpushed = _add_worktree(repo=repo, name="wt-unpushed", branch="feat/unpushed")
    _commit(cwd=unpushed, name="local-only.txt")
    detached = _add_worktree(repo=repo, name="wt-detached", branch=None)
    gone = _add_worktree(repo=repo, name="wt-gone", branch="feat/gone")
    shutil.rmtree(gone)
    locked = _add_worktree(repo=repo, name="wt-locked", branch="feat/locked")
    _git("worktree", "lock", str(locked), cwd=repo)
    return {
        "squash": squash,
        "closed": closed,
        "mirrors": mirrors,
        "open": in_use,
        "dirty": dirty,
        "moved": moved,
        "open_pr": open_pr,
        "unpushed": unpushed,
        "detached": detached,
        "gone": gone,
        "locked": locked,
        "prs": {
            "feat/squash": _pr(number=11, state="MERGED", head_oid=squash_head),
            "feat/closed": _pr(number=12, state="CLOSED", head_oid=closed_head),
            "feat/mirrors": _pr(number=13, state="MERGED", head_oid=mirrors_head),
            "feat/open": _pr(number=14, state="MERGED", head_oid=in_use_head),
            "feat/dirty": _pr(number=15, state="MERGED", head_oid=dirty_head),
            "feat/moved": _pr(number=16, state="MERGED", head_oid="0" * 40),
            "feat/open-pr": _pr(number=17, state="OPEN", head_oid=open_head),
            "feat/locked": _pr(number=18, state="MERGED", head_oid="1" * 40),
        },
    }


def _stub_pr_lookup(*, prs: dict[str, wp.PullRequestState]) -> wp.PullRequestLookup:
    async def lookup(*, branch: str, cwd: str) -> wp.PullRequestState:
        return prs.get(branch, wp.PullRequestState(known=True))

    return lookup


def _stub_workspaces(*, state: wp.WorkspaceState) -> wp.WorkspaceLookup:
    return AsyncMock(return_value=state)


def _survey(
    *,
    cwd: Path,
    prs: dict[str, wp.PullRequestState],
    workspaces: wp.WorkspaceState,
    paths: list[str] | None = None,
    base: str = "develop",
) -> Any:
    with use_cwd(str(cwd)):
        return asyncio.run(
            wp.worktree_prune_candidates(
                base=base,
                paths=paths,
                pr_lookup=_stub_pr_lookup(prs=prs),
                workspace_lookup=_stub_workspaces(state=workspaces),
            )
        )


@pytest.fixture
def survey(repo: Path, worktrees: dict[str, Any]) -> dict[str, Any]:
    workspaces = wp.WorkspaceState(
        known=True,
        open_by_path={str(worktrees["open"]): "w9Z"},
        source="read",
    )
    result = _survey(cwd=repo, prs=worktrees["prs"], workspaces=workspaces)
    assert isinstance(result, SuccessResult)
    return result.value


@pytest.fixture
def by_path(survey: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["path"]: item for item in survey["worktrees"]}


class TestSurveyClassification:
    @pytest.mark.parametrize(
        ("name", "expected_class", "expected_reason"),
        [
            ("squash", "remove", "merged (pr), PR #11"),
            ("mirrors", "remove", "merged (pr), PR #13"),
            ("closed", "ask", "PR #12 closed without merge"),
            ("detached", "ask", "no PR; HEAD is on base history"),
            ("open", "keep", "open in herdr workspace w9Z"),
            ("dirty", "keep", "1 uncommitted path(s)"),
            ("moved", "keep", "HEAD moved past merged PR #16"),
            ("open_pr", "keep", "PR #17 is open"),
            ("unpushed", "keep", "1 commit(s) on no remote"),
            ("gone", "keep", "path missing; `git worktree prune` clears its entry"),
            ("locked", "keep", "worktree is locked"),
        ],
    )
    def test_classifies_each_worktree(
        self,
        by_path: dict[str, dict[str, Any]],
        worktrees: dict[str, Any],
        name: str,
        expected_class: str,
        expected_reason: str,
    ) -> None:
        item = by_path[str(worktrees[name])]

        assert (item["class"], item["reason"]) == (expected_class, expected_reason)

    def test_keeps_the_main_checkout_it_runs_in(
        self,
        by_path: dict[str, dict[str, Any]],
        repo: Path,
    ) -> None:
        assert by_path[str(repo)]["reason"] == "main checkout"

    def test_mirrors_only_checkout_needs_force(
        self,
        by_path: dict[str, dict[str, Any]],
        worktrees: dict[str, Any],
    ) -> None:
        item = by_path[str(worktrees["mirrors"])]

        assert (item["force_required"], item["dirty_paths"], sorted(item["mirror_paths"])) == (
            True,
            [],
            [".agents/", ".codex/"],
        )

    def test_dirty_checkout_never_needs_force(
        self,
        by_path: dict[str, dict[str, Any]],
        worktrees: dict[str, Any],
    ) -> None:
        item = by_path[str(worktrees["dirty"])]

        assert (item["force_required"], item["dirty_paths"]) == (False, ["wt-dirty.txt"])

    def test_groups_paths_by_class(
        self, survey: dict[str, Any], worktrees: dict[str, Any]
    ) -> None:
        assert (sorted(survey["remove"]), sorted(survey["ask"])) == (
            sorted([str(worktrees["squash"]), str(worktrees["mirrors"])]),
            sorted([str(worktrees["closed"]), str(worktrees["detached"])]),
        )

    def test_reports_base_and_herdr_source(self, survey: dict[str, Any]) -> None:
        assert (survey["base"], survey["herdr"], survey["not_found"]) == (
            "origin/develop",
            "read",
            [],
        )

    def test_reports_pr_and_merge_details(
        self,
        by_path: dict[str, dict[str, Any]],
        worktrees: dict[str, Any],
    ) -> None:
        item = by_path[str(worktrees["squash"])]

        assert (
            item["pull_request"],
            item["merged_by"],
            item["unpushed_commits"],
            item["ahead_of_base"],
        ) == ({"number": 11, "state": "MERGED"}, "pr", 0, 1)

    def test_counts_unpushed_commits_ahead_of_base(
        self,
        by_path: dict[str, dict[str, Any]],
        worktrees: dict[str, Any],
    ) -> None:
        item = by_path[str(worktrees["unpushed"])]

        assert (item["unpushed_commits"], item["ahead_of_base"]) == (1, 1)

    def test_reports_last_commit_date(
        self,
        by_path: dict[str, dict[str, Any]],
        worktrees: dict[str, Any],
    ) -> None:
        assert by_path[str(worktrees["squash"])]["last_commit_at"] == _COMMIT_DATE


class TestSurveyScope:
    def test_keeps_the_checkout_the_session_runs_in(
        self,
        worktrees: dict[str, Any],
    ) -> None:
        result = _survey(
            cwd=worktrees["squash"],
            prs=worktrees["prs"],
            workspaces=wp.WorkspaceState(known=True),
            paths=[str(worktrees["squash"])],
        )

        assert result.value["worktrees"][0]["reason"] == "the checkout this session runs in"

    def test_symlinked_session_checkout_is_still_current(
        self,
        worktrees: dict[str, Any],
        tmp_path: Path,
    ) -> None:
        link = tmp_path / "link-to-squash"
        link.symlink_to(worktrees["squash"])

        result = _survey(
            cwd=link,
            prs=worktrees["prs"],
            workspaces=wp.WorkspaceState(known=True),
            paths=[str(link)],
        )

        assert (result.value["worktrees"][0]["reason"], result.value["not_found"]) == (
            "the checkout this session runs in",
            [],
        )

    def test_relative_paths_resolve_against_the_bound_checkout(
        self,
        repo: Path,
        worktrees: dict[str, Any],
    ) -> None:
        result = _survey(
            cwd=repo,
            prs=worktrees["prs"],
            workspaces=wp.WorkspaceState(known=True),
            paths=["../wt-squash"],
        )

        assert (
            [item["path"] for item in result.value["worktrees"]],
            result.value["not_found"],
        ) == ([str(worktrees["squash"])], [])

    def test_paths_limit_the_survey_and_report_unknown_ones(
        self,
        repo: Path,
        worktrees: dict[str, Any],
    ) -> None:
        result = _survey(
            cwd=repo,
            prs=worktrees["prs"],
            workspaces=wp.WorkspaceState(known=True),
            paths=[f"{worktrees['squash']}/", "/nowhere/else"],
        )

        assert (
            [item["path"] for item in result.value["worktrees"]],
            result.value["not_found"],
        ) == ([str(worktrees["squash"])], ["/nowhere/else"])

    def test_unknown_herdr_state_keeps_everything_removable(
        self,
        repo: Path,
        worktrees: dict[str, Any],
    ) -> None:
        result = _survey(
            cwd=repo,
            prs=worktrees["prs"],
            workspaces=wp.WorkspaceState(known=False, source="error: boom"),
            paths=[str(worktrees["squash"])],
        )

        assert result.value["worktrees"][0]["reason"] == "herdr workspace state unknown"

    def test_unknown_pr_state_keeps_the_worktree(
        self,
        repo: Path,
        worktrees: dict[str, Any],
    ) -> None:
        result = _survey(
            cwd=repo,
            prs={"feat/squash": wp.PullRequestState(known=False, error="rate limited")},
            workspaces=wp.WorkspaceState(known=True),
            paths=[str(worktrees["squash"])],
        )

        assert result.value["worktrees"][0]["reason"] == "PR state unknown: rate limited"

    def test_unreadable_base_keeps_the_worktree(
        self,
        repo: Path,
        worktrees: dict[str, Any],
    ) -> None:
        result = _survey(
            cwd=repo,
            prs=worktrees["prs"],
            workspaces=wp.WorkspaceState(known=True),
            paths=[str(worktrees["squash"])],
            base="no-such-base",
        )

        assert (result.value["base"], result.value["worktrees"][0]["reason"][:20]) == (
            "no-such-base",
            "state unreadable: fa",
        )

    def test_untracked_work_counts_even_when_status_hides_it(
        self,
        repo: Path,
        worktrees: dict[str, Any],
    ) -> None:
        _git("config", "status.showUntrackedFiles", "no", cwd=repo)
        (worktrees["squash"] / "notes.txt").write_text("unsaved idea\n")

        result = _survey(
            cwd=repo,
            prs=worktrees["prs"],
            workspaces=wp.WorkspaceState(known=True),
            paths=[str(worktrees["squash"])],
        )

        assert result.value["worktrees"][0]["reason"] == "1 uncommitted path(s)"

    def test_slashed_base_is_qualified_to_its_remote_ref(
        self,
        repo: Path,
        worktrees: dict[str, Any],
    ) -> None:
        _git("push", "-q", "origin", "develop:release/1.0", cwd=repo)
        _git("fetch", "-q", "origin", cwd=repo)

        result = _survey(
            cwd=repo,
            prs=worktrees["prs"],
            workspaces=wp.WorkspaceState(known=True),
            paths=[str(worktrees["squash"])],
            base="release/1.0",
        )

        assert result.value["base"] == "origin/release/1.0"

    def test_qualified_base_passes_through(
        self,
        repo: Path,
        worktrees: dict[str, Any],
    ) -> None:
        result = _survey(
            cwd=repo,
            prs=worktrees["prs"],
            workspaces=wp.WorkspaceState(known=True),
            paths=[str(worktrees["squash"])],
            base="origin/develop",
        )

        assert result.value["base"] == "origin/develop"

    def test_errors_outside_a_repository(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()

        result = _survey(cwd=outside, prs={}, workspaces=wp.WorkspaceState(known=True))

        assert isinstance(result, ErrorResult)


class TestSurveyGitFailures:
    @pytest.fixture
    def toplevel(self) -> Any:
        return completed(stdout="/repo\n")

    @pytest.mark.parametrize(
        ("listing", "expected"),
        [
            (completed(returncode=1, stderr="broken"), "broken"),
            (completed(stdout=""), "git worktree list reported no worktrees"),
            (
                completed(stdout="bare\nworktree /repo.git\nbare\n"),
                "git worktree list reported no worktrees",
            ),
        ],
    )
    def test_reports_listing_failures(
        self,
        toplevel: Any,
        listing: Any,
        expected: str,
    ) -> None:
        with patch.object(wp, "async_run", new=AsyncMock(side_effect=[toplevel, listing])):
            result = asyncio.run(wp.worktree_prune_candidates())

        assert result.error == expected


class TestParseWorktreeList:
    def test_parses_branch_detached_locked_and_prunable_entries(self) -> None:
        porcelain = (
            "worktree /repo\nHEAD aaa\nbranch refs/heads/develop\n\n"
            "worktree /wt/a\nHEAD bbb\ndetached\nlocked\n\n"
            "worktree /wt/b\nHEAD ccc\nbranch refs/heads/feat/b\nprunable gitdir missing\n"
        )

        assert wp.parse_worktree_list(porcelain=porcelain) == [
            wp.WorktreeEntry(path="/repo", head="aaa", branch="develop"),
            wp.WorktreeEntry(path="/wt/a", head="bbb", branch=None, locked=True),
            wp.WorktreeEntry(path="/wt/b", head="ccc", branch="feat/b", prunable=True),
        ]


class TestSplitStatus:
    @pytest.mark.parametrize(
        ("porcelain", "expected"),
        [
            ("", ((), ())),
            ("?? .agents/\n?? .codex/\n", ((), (".agents/", ".codex/"))),
            (" M .agents/x.md\n", ((".agents/x.md",), ())),
            ("?? notes.txt\n M src/a.py\n", (("notes.txt", "src/a.py"), ())),
            ("R  old.py -> new.py\n\n", (("new.py",), ())),
        ],
    )
    def test_separates_generated_mirrors(
        self,
        porcelain: str,
        expected: tuple[tuple[str, ...], tuple[str, ...]],
    ) -> None:
        assert wp.split_status(porcelain=porcelain) == expected


class TestSplitIgnored:
    @pytest.mark.parametrize(
        ("porcelain", "expected"),
        [
            ("", ()),
            ("!! .venv/\n!! node_modules/\n!! src/__pycache__/\n", ()),
            ("!! .pytest_cache/\n!! .ruff_cache/\n!! .mypy_cache/\n", ()),
            ("!! .env\n!! .venv/\n", (".env",)),
            ("!! build/\n?? notes.txt\n M a.py\n", ("build/",)),
            (
                "!! pkg/node_modules/x\n!! .claude/settings.local.json\n",
                (".claude/settings.local.json",),
            ),
        ],
    )
    def test_keeps_only_ignored_paths_outside_known_caches(
        self,
        porcelain: str,
        expected: tuple[str, ...],
    ) -> None:
        assert wp.split_ignored(porcelain=porcelain) == expected

    def test_ignored_entries_are_not_reported_as_dirty(self) -> None:
        assert wp.split_status(porcelain="!! .env\n") == ((), ())


class TestIgnoredFiles:
    def test_checkout_holding_only_an_ignored_file_is_kept(
        self,
        repo: Path,
        worktrees: dict[str, Any],
    ) -> None:
        squash = worktrees["squash"]
        (squash / ".gitignore").write_text(".env\n.venv/\n")
        _git("add", ".gitignore", cwd=squash)
        _git("commit", "-q", "-m", "ignore", cwd=squash)
        _git("push", "-q", "origin", "feat/squash", cwd=squash)
        head = _git("rev-parse", "HEAD", cwd=squash)
        (squash / ".env").write_text("SECRET=1\n")
        (squash / ".venv").mkdir()
        (squash / ".venv" / "pyvenv.cfg").write_text("cache\n")
        prs = {"feat/squash": _pr(number=11, state="MERGED", head_oid=head)}

        result = _survey(
            cwd=repo,
            prs=prs,
            workspaces=wp.WorkspaceState(known=True),
            paths=[str(squash)],
        )

        item = result.value["worktrees"][0]
        assert (item["class"], item["ignored_paths"], item["reason"]) == (
            "keep",
            [".env"],
            "1 ignored path(s) that removal would delete",
        )

    def test_checkout_holding_only_known_caches_stays_removable(
        self,
        repo: Path,
        worktrees: dict[str, Any],
    ) -> None:
        squash = worktrees["squash"]
        (squash / ".gitignore").write_text(".venv/\n")
        _git("add", ".gitignore", cwd=squash)
        _git("commit", "-q", "-m", "ignore", cwd=squash)
        _git("push", "-q", "origin", "feat/squash", cwd=squash)
        head = _git("rev-parse", "HEAD", cwd=squash)
        (squash / ".venv").mkdir()
        (squash / ".venv" / "pyvenv.cfg").write_text("cache\n")
        prs = {"feat/squash": _pr(number=11, state="MERGED", head_oid=head)}

        result = _survey(
            cwd=repo,
            prs=prs,
            workspaces=wp.WorkspaceState(known=True),
            paths=[str(squash)],
        )

        item = result.value["worktrees"][0]
        assert (item["class"], item["ignored_paths"]) == ("remove", [])


class TestAbsentHerdrSurvey:
    def test_herdr_in_use_but_absent_keeps_removable_checkouts(
        self,
        repo: Path,
        worktrees: dict[str, Any],
    ) -> None:
        result = _survey(
            cwd=repo,
            prs=worktrees["prs"],
            workspaces=wp.WorkspaceState(
                known=False,
                source="absent: herdr is in use but not on PATH",
            ),
            paths=[str(worktrees["squash"])],
        )

        assert (result.value["herdr"], result.value["worktrees"][0]["class"]) == (
            "absent: herdr is in use but not on PATH",
            "keep",
        )


class TestLatestPullRequest:
    @pytest.mark.parametrize(
        ("prs", "expected"),
        [
            ([], None),
            (["junk"], None),
            (
                [
                    {"number": 3, "state": "closed", "headRefOid": "a"},
                    {"number": 9, "state": "MERGED", "headRefOid": "b"},
                ],
                wp.PullRequestRef(number=9, state="MERGED", head_oid="b"),
            ),
        ],
    )
    def test_picks_the_newest(self, prs: list[Any], expected: Any) -> None:
        assert wp.latest_pull_request(prs=prs) == expected


class TestLookupPullRequest:
    @pytest.fixture(autouse=True)
    def gh_on_path(self) -> Iterator[None]:
        with patch.object(wp.shutil, "which", return_value="/usr/bin/gh"):
            yield

    def test_missing_gh_means_unknown_pr_state(self) -> None:
        with patch.object(wp.shutil, "which", return_value=None):
            state = asyncio.run(wp.lookup_pull_request(branch="feat/x", cwd="/repo"))

        assert state == wp.PullRequestState(
            known=False,
            error="gh is not installed or not on PATH",
        )

    @pytest.mark.parametrize(
        ("response", "expected"),
        [
            (
                completed(stdout='[{"number": 5, "state": "MERGED", "headRefOid": "abc"}]'),
                _pr(number=5, state="MERGED", head_oid="abc"),
            ),
            (completed(stdout=""), wp.PullRequestState(known=True)),
            (
                completed(returncode=1, stderr="auth"),
                wp.PullRequestState(known=False, error="auth"),
            ),
            (
                completed(returncode=1),
                wp.PullRequestState(known=False, error="gh pr list failed"),
            ),
            (
                completed(stdout="{nope"),
                wp.PullRequestState(known=False, error="gh pr list returned invalid JSON"),
            ),
            (
                completed(stdout="{}"),
                wp.PullRequestState(known=False, error="gh pr list returned a non-list"),
            ),
        ],
    )
    def test_maps_gh_output(self, response: Any, expected: wp.PullRequestState) -> None:
        with patch.object(wp, "async_run", new=AsyncMock(return_value=response)):
            assert asyncio.run(wp.lookup_pull_request(branch="feat/x", cwd="/repo")) == expected

    def test_queries_by_head_branch(self) -> None:
        runner = AsyncMock(return_value=completed(stdout="[]"))

        with patch.object(wp, "async_run", new=runner):
            asyncio.run(wp.lookup_pull_request(branch="feat/x", cwd="/repo"))

        assert runner.call_args.kwargs["args"][5:7] == ["--head", "feat/x"]


class TestParseHerdrWorkspaces:
    def test_keys_open_workspaces_by_resolved_path(self, tmp_path: Path) -> None:
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real)
        worktrees = [{"path": str(link), "open_workspace_id": "w7"}]

        assert wp.parse_herdr_workspaces(worktrees=worktrees) == {str(real): "w7"}


class TestLookupWorkspaces:
    @pytest.fixture
    def herdr_on_path(self) -> Iterator[None]:
        with patch.object(wp.shutil, "which", return_value="/usr/bin/herdr"):
            yield

    def test_absent_herdr_means_no_open_workspaces(self) -> None:
        with patch.object(wp.shutil, "which", return_value=None):
            state = asyncio.run(wp.lookup_workspaces(root="/repo"))

        assert state == wp.WorkspaceState(known=True, source="absent")

    def test_absent_herdr_with_home_directory_is_unknown(self, fake_home: Path) -> None:
        (fake_home / wp.HERDR_HOME_DIR).mkdir()

        with patch.object(wp.shutil, "which", return_value=None):
            state = asyncio.run(wp.lookup_workspaces(root="/repo"))

        assert state == wp.WorkspaceState(
            known=False,
            source="absent: herdr is in use but not on PATH",
        )

    def test_absent_herdr_with_env_marker_is_unknown(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(wp.HERDR_ENV_VAR, "1")

        with patch.object(wp.shutil, "which", return_value=None):
            state = asyncio.run(wp.lookup_workspaces(root="/repo"))

        assert state.known is False

    @pytest.mark.parametrize(
        ("response", "expected"),
        [
            (
                completed(
                    stdout=(
                        '{"result": {"worktrees": ['
                        '{"path": "/wt/a", "open_workspace_id": "w1"},'
                        '{"path": "/wt/b", "open_workspace_id": null}]}}'
                    )
                ),
                wp.WorkspaceState(known=True, open_by_path={"/wt/a": "w1"}, source="read"),
            ),
            (
                completed(stdout='{"result": {"worktrees": [{"path": "/wt/b"}]}}'),
                wp.WorkspaceState(
                    known=False,
                    source="error: herdr items lack path or open_workspace_id",
                ),
            ),
            (
                completed(stdout='{"result": {"worktrees": [{"open_workspace_id": "w1"}]}}'),
                wp.WorkspaceState(
                    known=False,
                    source="error: herdr items lack path or open_workspace_id",
                ),
            ),
            (
                completed(stdout='{"result": {"worktrees": ["junk"]}}'),
                wp.WorkspaceState(
                    known=False,
                    source="error: herdr items lack path or open_workspace_id",
                ),
            ),
            (
                completed(returncode=1, stderr="no server"),
                wp.WorkspaceState(known=False, source="error: no server"),
            ),
            (
                completed(returncode=1),
                wp.WorkspaceState(known=False, source="error: herdr worktree list failed"),
            ),
            (
                completed(stdout="{nope"),
                wp.WorkspaceState(known=False, source="error: herdr returned invalid JSON"),
            ),
            (
                completed(stdout="[]"),
                wp.WorkspaceState(known=False, source="error: herdr returned a non-object"),
            ),
            (
                completed(stdout="{}"),
                wp.WorkspaceState(
                    known=False,
                    source="error: herdr payload has no result.worktrees list",
                ),
            ),
            (
                completed(stdout='{"result": "nope"}'),
                wp.WorkspaceState(
                    known=False,
                    source="error: herdr payload has no result.worktrees list",
                ),
            ),
            (
                completed(stdout='{"result": {"worktrees": {}}}'),
                wp.WorkspaceState(
                    known=False,
                    source="error: herdr payload has no result.worktrees list",
                ),
            ),
            (
                completed(stdout='{"result": {"worktrees": []}}'),
                wp.WorkspaceState(known=True, source="read"),
            ),
        ],
    )
    def test_maps_herdr_output(
        self,
        herdr_on_path: None,
        response: Any,
        expected: wp.WorkspaceState,
    ) -> None:
        with patch.object(wp, "async_run", new=AsyncMock(return_value=response)):
            assert asyncio.run(wp.lookup_workspaces(root="/repo")) == expected


class TestClassify:
    def test_unknown_unpushed_count_keeps_the_worktree(self) -> None:
        facts = wp.WorktreeFacts(
            entry=wp.WorktreeEntry(path="/wt/a", head="abc", branch="feat/a"),
            unpushed_commits=None,
        )

        assert wp.classify(facts=facts).reason == "unpushed commit count unknown"

    def test_merged_by_ancestry_still_requires_a_merged_pr_to_remove(self) -> None:
        facts = wp.WorktreeFacts(
            entry=wp.WorktreeEntry(path="/wt/a", head="abc", branch="feat/a"),
            on_base=True,
            pull_request=_pr(number=4, state="MERGED", head_oid="other"),
        )

        assert (wp.classify(facts=facts).prune_class, facts.merged_by) == (
            wp.PruneClass.REMOVE,
            "ancestry",
        )

    def test_branch_without_pr_off_base_asks(self) -> None:
        facts = wp.WorktreeFacts(
            entry=wp.WorktreeEntry(path="/wt/a", head="abc", branch="feat/a"),
        )

        assert wp.classify(facts=facts).reason == "branch has no PR"
