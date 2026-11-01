"""Tests for the supervisor's per-folder workspace lookup (GH-1722)."""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from dev10x.comm.overwatch.workspace import (
    REMOTE_URL,
    REV_PARSE,
    Workspace,
    github_url,
    issue_url,
    pr_number,
    pr_url,
    read_workspace,
)

CWD = "/work/.herdr/worktrees/Dev10x-Claude/janusz-poc"
REV_PARSE_OUT = f"/work/dx/Dev10x-Claude/.git\n{CWD}\njanusz/GH-1722/poc/status-bar\n"
REMOTE_OUT = "git@github.com:Dev10x-Guru/Dev10x-Claude.git\n"


class FakeGit:
    def __init__(self, *, outputs: dict[str, tuple[int, str]]) -> None:
        self.outputs = outputs
        self.calls: list[dict[str, Any]] = []

    def __call__(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append({"args": args, **kwargs})
        returncode, stdout = self.outputs[" ".join(args)]
        return subprocess.CompletedProcess(args=args, returncode=returncode, stdout=stdout)


@pytest.fixture
def git() -> FakeGit:
    return FakeGit(
        outputs={" ".join(REV_PARSE): (0, REV_PARSE_OUT), " ".join(REMOTE_URL): (0, REMOTE_OUT)}
    )


class TestReadWorkspace:
    def test_worktree_maps_to_its_main_project(self, git: FakeGit) -> None:
        assert read_workspace(cwd=CWD, runner=git) == Workspace(
            project="Dev10x-Claude",
            root=CWD,
            branch="janusz/GH-1722/poc/status-bar",
            issue="GH-1722",
            repo_url="https://github.com/Dev10x-Guru/Dev10x-Claude",
        )

    def test_runs_git_in_the_session_folder(self, git: FakeGit) -> None:
        read_workspace(cwd=CWD, runner=git)

        assert {call["cwd"] for call in git.calls} == {CWD}

    def test_bare_common_dir(self, git: FakeGit) -> None:
        git.outputs[" ".join(REV_PARSE)] = (0, f"/srv/repos/tt-pos.git\n{CWD}\nmain\n")

        workspace = read_workspace(cwd=CWD, runner=git)

        assert (workspace.project, workspace.issue) == ("tt-pos", "")

    def test_detached_head_has_no_branch(self, git: FakeGit) -> None:
        git.outputs[" ".join(REV_PARSE)] = (0, f"/r/.git\n{CWD}\nHEAD\n")

        assert read_workspace(cwd=CWD, runner=git).branch == ""

    def test_no_remote(self, git: FakeGit) -> None:
        git.outputs[" ".join(REMOTE_URL)] = (2, "")

        assert read_workspace(cwd=CWD, runner=git).repo_url == ""

    @pytest.mark.parametrize(
        "outcome",
        [(128, ""), (0, "only-one-line\n")],
        ids=["not-a-repo", "short-output"],
    )
    def test_falls_back_to_the_folder(self, git: FakeGit, outcome: tuple[int, str]) -> None:
        git.outputs[" ".join(REV_PARSE)] = outcome

        assert read_workspace(cwd="/work/tt/notes", runner=git) == Workspace(
            project="notes", root="/work/tt/notes"
        )

    @pytest.mark.parametrize(
        "error",
        [FileNotFoundError("gone"), subprocess.TimeoutExpired(cmd="git", timeout=5)],
        ids=["missing-folder", "timeout"],
    )
    def test_git_failure_falls_back(self, error: Exception) -> None:
        def runner(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            raise error

        assert read_workspace(cwd="/gone/away", runner=runner).project == "away"

    def test_empty_cwd(self, git: FakeGit) -> None:
        assert (read_workspace(cwd="", runner=git), git.calls) == (
            Workspace(project="", root=""),
            [],
        )


class TestLinks:
    @pytest.mark.parametrize(
        ("remote", "expected"),
        [
            ("git@github.com:Dev10x-Guru/Dev10x-Claude.git", "Dev10x-Guru/Dev10x-Claude"),
            ("https://github.com/tiretutor/tt-pos", "tiretutor/tt-pos"),
            ("https://github.com/tiretutor/tt-pos.git/", "tiretutor/tt-pos"),
            ("ssh://git@github.com/a/b.c.git", "a/b.c"),
        ],
    )
    def test_github_remotes(self, remote: str, expected: str) -> None:
        assert github_url(remote=remote) == f"https://github.com/{expected}"

    def test_other_hosts_get_no_link(self) -> None:
        assert github_url(remote="git@gitlab.com:a/b.git") == ""

    @pytest.mark.parametrize(
        ("status_line", "expected"),
        [("GH-1  PR#1718  Opus", "1718"), ("PR #9", "9"), ("no pr here", "")],
    )
    def test_pr_number(self, status_line: str, expected: str) -> None:
        assert pr_number(status_line=status_line) == expected

    @pytest.mark.parametrize(
        ("issue", "repo_url", "expected"),
        [
            ("GH-12", "https://github.com/a/b", "https://github.com/a/b/issues/12"),
            ("PAY-12", "https://github.com/a/b", ""),
            ("GH-12", "", ""),
        ],
        ids=["github", "other-tracker", "no-repo"],
    )
    def test_issue_url(self, issue: str, repo_url: str, expected: str) -> None:
        assert issue_url(issue=issue, repo_url=repo_url) == expected

    @pytest.mark.parametrize(
        ("pr", "repo_url", "expected"),
        [("7", "https://github.com/a/b", "https://github.com/a/b/pull/7"), ("", "x", "")],
    )
    def test_pr_url(self, pr: str, repo_url: str, expected: str) -> None:
        assert pr_url(pr=pr, repo_url=repo_url) == expected
