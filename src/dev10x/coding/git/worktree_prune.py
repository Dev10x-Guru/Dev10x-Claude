"""Classify every worktree of a repo for pruning in one call (GH-1930).

The decision is a pure function over probed facts;
``worktree_prune_candidates`` is the wiring that runs git, gh and herdr.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from functools import cached_property
from pathlib import Path
from typing import Any

from dev10x.coding.skills.orchestration.stranded_work import parse_porcelain
from dev10x.domain.common.result import Result, err, ok
from dev10x.subprocess_utils import async_run

GENERATED_MIRROR_DIRS = (".agents/", ".codex/")
_UNTRACKED_PREFIX = "??"
_IGNORED_PREFIX = "!!"
KNOWN_CACHE_DIRS = frozenset(
    {".venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
)
HERDR_ENV_VAR = "HERDR_ENV"
HERDR_HOME_DIR = ".herdr"
_TIMEOUT_SECONDS = 30
_PR_LOOKUP_LIMIT = 20

PullRequestLookup = Callable[..., Awaitable["PullRequestState"]]
WorkspaceLookup = Callable[..., Awaitable["WorkspaceState"]]


class PruneClass(StrEnum):
    REMOVE = "remove"
    ASK = "ask"
    KEEP = "keep"


@dataclass(frozen=True)
class WorktreeEntry:
    path: str
    head: str
    branch: str | None
    locked: bool = False
    prunable: bool = False

    @cached_property
    def real_path(self) -> str:
        return os.path.realpath(self.path)


@dataclass(frozen=True)
class PullRequestRef:
    number: int
    state: str
    head_oid: str


@dataclass(frozen=True)
class PullRequestState:
    known: bool
    latest: PullRequestRef | None = None
    error: str = ""


@dataclass(frozen=True)
class WorkspaceState:
    known: bool
    open_by_path: dict[str, str] = field(default_factory=dict)
    source: str = "absent"


@dataclass(frozen=True)
class WorktreeFacts:
    entry: WorktreeEntry
    is_main: bool = False
    is_current: bool = False
    exists: bool = True
    probe_error: str = ""
    dirty_paths: tuple[str, ...] = ()
    mirror_paths: tuple[str, ...] = ()
    ignored_paths: tuple[str, ...] = ()
    unpushed_commits: int | None = 0
    ahead_of_base: int | None = 0
    on_base: bool = False
    last_commit_at: str = ""
    pull_request: PullRequestState = PullRequestState(known=True)
    workspaces_known: bool = True
    open_workspace_id: str = ""

    @property
    def merged_by(self) -> str | None:
        latest = self.pull_request.latest
        if latest is not None and latest.state == "MERGED" and latest.head_oid == self.entry.head:
            return "pr"
        if self.on_base:
            return "ancestry"
        return None


@dataclass(frozen=True)
class Classification:
    facts: WorktreeFacts
    prune_class: PruneClass
    reason: str

    def to_dict(self) -> dict[str, Any]:
        facts = self.facts
        latest = facts.pull_request.latest
        return {
            "path": facts.entry.path,
            "branch": facts.entry.branch,
            "head": facts.entry.head,
            "class": self.prune_class.value,
            "reason": self.reason,
            "dirty_paths": list(facts.dirty_paths),
            "mirror_paths": list(facts.mirror_paths),
            "ignored_paths": list(facts.ignored_paths),
            "force_required": bool(facts.mirror_paths) and not facts.dirty_paths,
            "unpushed_commits": facts.unpushed_commits,
            "ahead_of_base": facts.ahead_of_base,
            "merged_by": facts.merged_by,
            "pull_request": (
                {"number": latest.number, "state": latest.state} if latest is not None else None
            ),
            "open_workspace_id": facts.open_workspace_id or None,
            "last_commit_at": facts.last_commit_at or None,
        }


def parse_worktree_list(*, porcelain: str) -> list[WorktreeEntry]:
    entries: list[WorktreeEntry] = []
    for block in porcelain.strip().split("\n\n"):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            key, _, value = line.partition(" ")
            fields[key] = value
        if "worktree" not in fields or "bare" in fields:
            continue
        branch = fields.get("branch", "").removeprefix("refs/heads/") or None
        entries.append(
            WorktreeEntry(
                path=fields["worktree"],
                head=fields.get("HEAD", ""),
                branch=branch,
                locked="locked" in fields,
                prunable="prunable" in fields,
            )
        )
    return entries


def split_status(*, porcelain: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    dirty: list[str] = []
    mirrors: list[str] = []
    for line in porcelain.splitlines():
        if line.startswith(_IGNORED_PREFIX):
            continue
        paths = parse_porcelain(porcelain=line)
        if not paths:
            continue
        path = paths[0]
        is_untracked = line.startswith(_UNTRACKED_PREFIX)
        if is_untracked and path.startswith(GENERATED_MIRROR_DIRS):
            mirrors.append(path)
        else:
            dirty.append(path)
    return tuple(dirty), tuple(mirrors)


def split_ignored(*, porcelain: str) -> tuple[str, ...]:
    ignored: list[str] = []
    for line in porcelain.splitlines():
        if not line.startswith(_IGNORED_PREFIX):
            continue
        path = line[len(_IGNORED_PREFIX) :].strip()
        if path and not KNOWN_CACHE_DIRS.intersection(path.rstrip("/").split("/")):
            ignored.append(path)
    return tuple(ignored)


def latest_pull_request(*, prs: list[dict[str, Any]]) -> PullRequestRef | None:
    refs = [
        PullRequestRef(
            number=int(pr["number"]),
            state=str(pr.get("state", "")).upper(),
            head_oid=str(pr.get("headRefOid", "")),
        )
        for pr in prs
        if isinstance(pr, dict) and "number" in pr
    ]
    if not refs:
        return None
    return max(refs, key=lambda ref: ref.number)


def parse_herdr_workspaces(*, worktrees: list[Any]) -> dict[str, str]:
    return {
        os.path.realpath(str(item["path"])): str(item["open_workspace_id"])
        for item in worktrees
        if isinstance(item, dict) and item.get("path") and item.get("open_workspace_id")
    }


def has_unexpected_herdr_items(*, worktrees: list[Any]) -> bool:
    return any(
        not isinstance(item, dict) or "path" not in item or "open_workspace_id" not in item
        for item in worktrees
    )


def herdr_in_use() -> bool:
    return HERDR_ENV_VAR in os.environ or (Path.home() / HERDR_HOME_DIR).exists()


def _keep_reason(*, facts: WorktreeFacts) -> str | None:
    if facts.is_main:
        return "main checkout"
    if facts.is_current:
        return "the checkout this session runs in"
    if not facts.exists or facts.entry.prunable:
        return "path missing; `git worktree prune` clears its entry"
    if facts.probe_error:
        return f"state unreadable: {facts.probe_error}"
    if facts.entry.locked:
        return "worktree is locked"
    if not facts.workspaces_known:
        return "herdr workspace state unknown"
    if facts.open_workspace_id:
        return f"open in herdr workspace {facts.open_workspace_id}"
    if facts.dirty_paths:
        return f"{len(facts.dirty_paths)} uncommitted path(s)"
    if facts.ignored_paths:
        return f"{len(facts.ignored_paths)} ignored path(s) that removal would delete"
    if facts.unpushed_commits is None:
        return "unpushed commit count unknown"
    if facts.unpushed_commits:
        return f"{facts.unpushed_commits} commit(s) on no remote"
    if not facts.pull_request.known:
        return f"PR state unknown: {facts.pull_request.error}"
    return None


def _decide(*, facts: WorktreeFacts) -> tuple[PruneClass, str]:
    keep_reason = _keep_reason(facts=facts)
    if keep_reason is not None:
        return PruneClass.KEEP, keep_reason

    latest = facts.pull_request.latest
    if latest is None:
        reason = "no PR; HEAD is on base history" if facts.on_base else "branch has no PR"
        return PruneClass.ASK, reason
    if latest.state == "MERGED":
        if facts.merged_by is None:
            return PruneClass.KEEP, f"HEAD moved past merged PR #{latest.number}"
        return PruneClass.REMOVE, f"merged ({facts.merged_by}), PR #{latest.number}"
    if latest.state == "CLOSED":
        return PruneClass.ASK, f"PR #{latest.number} closed without merge"
    return PruneClass.KEEP, f"PR #{latest.number} is {latest.state.lower()}"


def classify(*, facts: WorktreeFacts) -> Classification:
    prune_class, reason = _decide(facts=facts)
    return Classification(facts=facts, prune_class=prune_class, reason=reason)


async def _git(*, args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    return await async_run(args=["git", *args], cwd=cwd, timeout=_TIMEOUT_SECONDS)


async def lookup_pull_request(*, branch: str, cwd: str) -> PullRequestState:
    if shutil.which("gh") is None:
        return PullRequestState(known=False, error="gh is not installed or not on PATH")
    result = await async_run(
        args=[
            "gh",
            "pr",
            "list",
            "--state",
            "all",
            "--head",
            branch,
            "--limit",
            str(_PR_LOOKUP_LIMIT),
            "--json",
            "number,state,headRefOid",
        ],
        cwd=cwd,
        timeout=_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        return PullRequestState(known=False, error=result.stderr.strip() or "gh pr list failed")
    try:
        prs = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return PullRequestState(known=False, error="gh pr list returned invalid JSON")
    if not isinstance(prs, list):
        return PullRequestState(known=False, error="gh pr list returned a non-list")
    return PullRequestState(known=True, latest=latest_pull_request(prs=prs))


async def lookup_workspaces(*, root: str) -> WorkspaceState:
    if shutil.which("herdr") is None:
        if herdr_in_use():
            return WorkspaceState(known=False, source="absent: herdr is in use but not on PATH")
        return WorkspaceState(known=True, source="absent")
    result = await async_run(
        args=["herdr", "worktree", "list", "--cwd", root],
        timeout=_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or "herdr worktree list failed"
        return WorkspaceState(known=False, source=f"error: {detail}")
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return WorkspaceState(known=False, source="error: herdr returned invalid JSON")
    if not isinstance(payload, dict):
        return WorkspaceState(known=False, source="error: herdr returned a non-object")
    listing = payload.get("result")
    worktrees = listing.get("worktrees") if isinstance(listing, dict) else None
    if not isinstance(worktrees, list):
        return WorkspaceState(
            known=False,
            source="error: herdr payload has no result.worktrees list",
        )
    if has_unexpected_herdr_items(worktrees=worktrees):
        return WorkspaceState(
            known=False,
            source="error: herdr items lack path or open_workspace_id",
        )
    return WorkspaceState(
        known=True,
        open_by_path=parse_herdr_workspaces(worktrees=worktrees),
        source="read",
    )


def _count(*, output: str) -> int | None:
    count = output.strip()
    return int(count) if count.isdigit() else None


async def _probe_entry(
    *,
    entry: WorktreeEntry,
    base_ref: str,
    is_main: bool,
    is_current: bool,
    workspaces: WorkspaceState,
    pr_lookup: PullRequestLookup,
) -> WorktreeFacts:
    identity = WorktreeFacts(
        entry=entry,
        is_main=is_main,
        is_current=is_current,
        workspaces_known=workspaces.known,
        open_workspace_id=workspaces.open_by_path.get(entry.real_path, ""),
    )
    if not Path(entry.path).is_dir():
        return replace(identity, exists=False)

    probes = await asyncio.gather(
        _git(
            args=["status", "--porcelain", "--ignored", "--untracked-files=normal"],
            cwd=entry.path,
        ),
        _git(args=["rev-list", "--count", "HEAD", "--not", "--remotes"], cwd=entry.path),
        _git(args=["rev-list", "--count", f"{base_ref}..HEAD"], cwd=entry.path),
        _git(args=["log", "-1", "--format=%cI"], cwd=entry.path),
    )
    status, unpushed, ahead, last_commit = probes
    failed = next((probe for probe in probes if probe.returncode != 0), None)
    if failed is not None:
        return replace(identity, probe_error=failed.stderr.strip() or "git probe failed")

    dirty, mirrors = split_status(porcelain=status.stdout)
    pull_request = (
        await pr_lookup(branch=entry.branch, cwd=entry.path)
        if entry.branch
        else PullRequestState(known=True)
    )
    ahead_of_base = _count(output=ahead.stdout)
    return replace(
        identity,
        dirty_paths=dirty,
        mirror_paths=mirrors,
        ignored_paths=split_ignored(porcelain=status.stdout),
        unpushed_commits=_count(output=unpushed.stdout),
        ahead_of_base=ahead_of_base,
        on_base=ahead_of_base == 0,
        last_commit_at=last_commit.stdout.strip(),
        pull_request=pull_request,
    )


async def _resolve_base_ref(*, base: str, cwd: str) -> str:
    if base.startswith("origin/"):
        return base
    remote = f"origin/{base}"
    verified = await _git(args=["rev-parse", "--verify", "--quiet", remote], cwd=cwd)
    return remote if verified.returncode == 0 else base


async def worktree_prune_candidates(
    *,
    base: str = "develop",
    paths: list[str] | None = None,
    pr_lookup: PullRequestLookup = lookup_pull_request,
    workspace_lookup: WorkspaceLookup = lookup_workspaces,
) -> Result[dict[str, Any]]:
    toplevel = await _git(args=["rev-parse", "--show-toplevel"])
    if toplevel.returncode != 0:
        return err(toplevel.stderr.strip() or "not inside a git repository")
    current = os.path.realpath(toplevel.stdout.strip())

    listing = await _git(args=["worktree", "list", "--porcelain"], cwd=current)
    if listing.returncode != 0:
        return err(listing.stderr.strip() or "git worktree list failed")
    entries = parse_worktree_list(porcelain=listing.stdout)
    if not entries:
        return err("git worktree list reported no worktrees")
    main_entry = entries[0]

    requested = {os.path.realpath(os.path.join(current, path)): path for path in paths or []}
    selected = [entry for entry in entries if not requested or entry.real_path in requested]
    known_paths = {entry.real_path for entry in entries}

    base_ref, workspaces = await asyncio.gather(
        _resolve_base_ref(base=base, cwd=current),
        workspace_lookup(root=main_entry.path),
    )
    facts = await asyncio.gather(
        *(
            _probe_entry(
                entry=entry,
                base_ref=base_ref,
                is_main=entry is main_entry,
                is_current=entry.real_path == current,
                workspaces=workspaces,
                pr_lookup=pr_lookup,
            )
            for entry in selected
        )
    )
    classified = [classify(facts=item).to_dict() for item in facts]
    return ok(
        {
            "base": base_ref,
            "herdr": workspaces.source,
            "worktrees": classified,
            **{
                prune_class.value: [
                    item["path"] for item in classified if item["class"] == prune_class.value
                ]
                for prune_class in PruneClass
            },
            "not_found": sorted(
                original for resolved, original in requested.items() if resolved not in known_paths
            ),
        }
    )
