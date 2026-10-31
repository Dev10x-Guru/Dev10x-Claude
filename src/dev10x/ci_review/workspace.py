from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from dev10x.ci_review.process import run_checked
from dev10x.core.domain.common.result import ErrorResult, Result, err, ok

log = logging.getLogger(__name__)

SCRIPTS_DIR: str = ".github/scripts/claude-pr-context"
BUILD_SCRIPT_PATH: str = f"{SCRIPTS_DIR}/build-claude-inputs.sh"

# claude-code-action v1.0.250, src/github/operations/restore-config.ts.
SENSITIVE_PATHS: tuple[str, ...] = (
    ".claude",
    ".mcp.json",
    ".claude.json",
    ".gitmodules",
    ".ripgreprc",
    "CLAUDE.md",
    "CLAUDE.local.md",
    ".husky",
)
PR_SNAPSHOT_DIR: str = ".claude-pr"
SNAPSHOT_EXCLUDE_LINE: str = "/.claude-pr/"
SYMLINK_PLACEHOLDER: str = "[symlink in the PR, not copied by dev10x ci-review]\n"

HYGIENE_MARKER: str = "<!-- dev10x-pr-hygiene -->"
HYGIENE_AUTHOR: str = "github-actions[bot]"
CONTEXT_DIR: str = ".claude-ci/pr-context"

_GIT_TIMEOUT_SECONDS: float = 300


@dataclass(frozen=True)
class Refs:
    base_sha: str
    merge_sha: str


@dataclass(frozen=True)
class Workspace:
    repo_root: Path
    run_dir: Path
    checkout: Path
    scripts: Path
    base_sha: str


def cache_root() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "dev10x" / "ci-review"


def run_dir_for(*, repo: str, pr: int, workflow: str, now: datetime) -> Path:
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    return cache_root() / repo.replace("/", "-") / f"pr-{pr}" / f"{stamp}-{workflow}"


def fetch_refs(*, repo_root: Path, base: str, pr: int) -> Result[Refs]:
    fetched = _git(repo_root=repo_root, args=["git", "fetch", "--no-tags", "origin", base])
    if isinstance(fetched, ErrorResult):
        return fetched
    base_sha = _git(repo_root=repo_root, args=["git", "rev-parse", "FETCH_HEAD"])
    if isinstance(base_sha, ErrorResult):
        return base_sha
    fetched = _git(
        repo_root=repo_root,
        args=["git", "fetch", "--no-tags", "origin", f"refs/pull/{pr}/merge"],
    )
    if isinstance(fetched, ErrorResult):
        return err(
            f"PR #{pr} has no merge ref; it may conflict with {base}",
            **fetched.details,
        )
    merge_sha = _git(repo_root=repo_root, args=["git", "rev-parse", "FETCH_HEAD"])
    if isinstance(merge_sha, ErrorResult):
        return merge_sha
    return ok(Refs(base_sha=base_sha.value.strip(), merge_sha=merge_sha.value.strip()))


def read_blob(*, repo_root: Path, sha: str, path: str) -> Result[str]:
    return _git(repo_root=repo_root, args=["git", "show", f"{sha}:{path}"])


def require_base_scripts(*, repo_root: Path, base: str, base_sha: str) -> Result[None]:
    found = _git(
        repo_root=repo_root, args=["git", "cat-file", "-e", f"{base_sha}:{BUILD_SCRIPT_PATH}"]
    )
    if isinstance(found, ErrorResult):
        return err(
            f"{base} has no {BUILD_SCRIPT_PATH} yet — skipping rather than running "
            "this PR's own copy."
        )
    return ok(None)


def create_workspace(*, repo_root: Path, run_dir: Path, refs: Refs) -> Result[Workspace]:
    run_dir.mkdir(parents=True, exist_ok=True)
    checkout = run_dir / "checkout"
    added = _git(
        repo_root=repo_root,
        args=["git", "worktree", "add", "--detach", str(checkout), refs.merge_sha],
    )
    if isinstance(added, ErrorResult):
        return added
    scripts = run_dir / "scripts"
    scripts.mkdir(exist_ok=True)
    archive = run_dir / "scripts.tar"
    for args in (
        ["git", "archive", "--format=tar", "-o", str(archive), refs.base_sha, SCRIPTS_DIR],
        ["tar", "-x", "-f", str(archive), "-C", str(scripts), "--strip-components=3"],
    ):
        step = _git(repo_root=repo_root, args=args)
        if isinstance(step, ErrorResult):
            return step
    return ok(
        Workspace(
            repo_root=repo_root,
            run_dir=run_dir,
            checkout=checkout,
            scripts=scripts,
            base_sha=refs.base_sha,
        )
    )


def apply_rules(*, workspace: Workspace, rules: str, keep_pr_head: bool) -> Result[None]:
    if rules == "head":
        log.warning(
            "--rules head: the review reads the PR's own instructions; CI reads the base's"
        )
        return ok(None)
    stage_args = [str(workspace.scripts / "stage-trusted.sh"), workspace.base_sha]
    if keep_pr_head:
        stage_args.append("--keep-pr-head")
    staged = run_checked(args=stage_args, cwd=workspace.checkout, timeout=_GIT_TIMEOUT_SECONDS)
    if isinstance(staged, ErrorResult):
        return staged
    return restore_config_from_base(checkout=workspace.checkout, base_sha=workspace.base_sha)


def restore_config_from_base(*, checkout: Path, base_sha: str) -> Result[None]:
    snapshot = checkout / PR_SNAPSHOT_DIR
    for relative in SENSITIVE_PATHS:
        _snapshot(source=checkout / relative, target=snapshot / relative)
    for relative in SENSITIVE_PATHS:
        _remove(path=checkout / relative)
    for relative in SENSITIVE_PATHS:
        # The action ignores paths the base lacks, and so does the replay.
        run_checked(
            args=["git", "checkout", base_sha, "--", relative],
            cwd=checkout,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    reset = run_checked(
        args=["git", "reset", "-q", "--", *SENSITIVE_PATHS],
        cwd=checkout,
        timeout=_GIT_TIMEOUT_SECONDS,
    )
    if isinstance(reset, ErrorResult):
        return reset
    exclude = run_checked(
        args=["git", "rev-parse", "--git-path", "info/exclude"],
        cwd=checkout,
        timeout=_GIT_TIMEOUT_SECONDS,
    )
    if isinstance(exclude, ErrorResult):
        return exclude
    _append_exclude(path=checkout / exclude.value.strip())
    return ok(None)


def _snapshot(*, source: Path, target: Path) -> None:
    # The action dereferences a link only when it points at tracked content;
    # a placeholder for every link is the safe subset of that.
    if source.is_symlink():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(SYMLINK_PLACEHOLDER, encoding="utf-8")
        return
    if source.is_dir():
        for child in sorted(source.iterdir()):
            _snapshot(source=child, target=target / child.name)
        return
    if source.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _remove(*, path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _append_exclude(*, path: Path) -> None:
    current = path.read_text(encoding="utf-8") if path.is_file() else ""
    if SNAPSHOT_EXCLUDE_LINE in current.splitlines():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    separator = "" if not current or current.endswith("\n") else "\n"
    path.write_text(f"{current}{separator}{SNAPSHOT_EXCLUDE_LINE}\n", encoding="utf-8")


def gather_context(*, workspace: Workspace, repo: str, pr: int) -> Result[None]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"GH_TOKEN", "GITHUB_TOKEN", "GITHUB_OUTPUT"}
    }
    env.update({"PR_NUMBER": str(pr), "GITHUB_REPOSITORY": repo})
    gathered = run_checked(
        args=[str(workspace.scripts / "gather-pr-context.sh")],
        cwd=workspace.checkout,
        env=env,
        timeout=_GIT_TIMEOUT_SECONDS,
    )
    if isinstance(gathered, ErrorResult):
        return gathered
    return ok(None)


def write_prior_hygiene_comment(*, checkout: Path) -> Result[int | None]:
    context = checkout / CONTEXT_DIR
    try:
        comments: list[dict[str, Any]] = json.loads(
            (context / "issue-comments.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        return err(f"cannot read {CONTEXT_DIR}/issue-comments.json: {exc}")
    prior = [
        comment
        for comment in comments
        if comment.get("user") == HYGIENE_AUTHOR and HYGIENE_MARKER in (comment.get("body") or "")
    ]
    chosen = prior[-1] if prior else {}
    (context / "prior-hygiene-comment.json").write_text(
        json.dumps(chosen, indent=2) + "\n", encoding="utf-8"
    )
    return ok(chosen.get("id"))


def remove_workspace(*, workspace: Workspace) -> Result[None]:
    removed = _git(
        repo_root=workspace.repo_root,
        args=["git", "worktree", "remove", "--force", str(workspace.checkout)],
    )
    if isinstance(removed, ErrorResult):
        return removed
    return ok(None)


def _git(*, repo_root: Path, args: list[str]) -> Result[str]:
    return run_checked(args=args, cwd=repo_root, timeout=_GIT_TIMEOUT_SECONDS)
