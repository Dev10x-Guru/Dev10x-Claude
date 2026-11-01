from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePath

from dev10x.subprocess_utils import run

GIT_TIMEOUT_SECONDS = 5
REV_PARSE = [
    "git",
    "rev-parse",
    "--path-format=absolute",
    "--git-common-dir",
    "--show-toplevel",
    "--abbrev-ref",
    "HEAD",
]
REMOTE_URL = ["git", "remote", "get-url", "origin"]
ISSUE_IN_BRANCH = re.compile(r"(?<![A-Za-z0-9])([A-Z][A-Z0-9]+-\d+)(?![0-9])")
PR_IN_STATUS = re.compile(r"\bPR\s?#(\d+)\b")
GITHUB_REMOTE = re.compile(
    r"^(?:git@github\.com:|ssh://git@github\.com/|https://github\.com/)"
    r"(?P<slug>[\w.-]+/[\w.-]+?)(?:\.git)?/?$"
)
GITHUB_ISSUE = re.compile(r"^GH-(\d+)$")

Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class Workspace:
    project: str
    root: str
    branch: str = ""
    issue: str = ""
    repo_url: str = ""


def _git(*, args: list[str], cwd: str, runner: Runner) -> list[str] | None:
    try:
        result = runner(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.splitlines()


def _project(*, common_dir: str) -> str:
    path = PurePath(common_dir)
    if path.name == ".git":
        path = path.parent
    return path.name.removesuffix(".git")


def github_url(*, remote: str) -> str:
    match = GITHUB_REMOTE.match(remote.strip())
    return f"https://github.com/{match.group('slug')}" if match else ""


def read_workspace(*, cwd: str, runner: Runner = run) -> Workspace:
    fallback = Workspace(project=PurePath(cwd).name or cwd, root=cwd)
    if not cwd:
        return fallback
    lines = _git(args=REV_PARSE, cwd=cwd, runner=runner)
    if not lines or len(lines) < 3:
        return fallback
    common_dir, root, branch = lines[0], lines[1], lines[2]
    branch = "" if branch == "HEAD" else branch
    issue = ISSUE_IN_BRANCH.search(branch)
    remote = _git(args=REMOTE_URL, cwd=cwd, runner=runner)
    return Workspace(
        project=_project(common_dir=common_dir),
        root=root,
        branch=branch,
        issue=issue.group(1) if issue else "",
        repo_url=github_url(remote=remote[0]) if remote else "",
    )


def pr_number(*, status_line: str) -> str:
    match = PR_IN_STATUS.search(status_line)
    return match.group(1) if match else ""


def issue_url(*, issue: str, repo_url: str) -> str:
    match = GITHUB_ISSUE.match(issue)
    return f"{repo_url}/issues/{match.group(1)}" if match and repo_url else ""


def pr_url(*, pr: str, repo_url: str) -> str:
    return f"{repo_url}/pull/{pr}" if pr and repo_url else ""
