from __future__ import annotations

import json
import re
import secrets
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from dev10x.subprocess_utils import run

HERDR_TIMEOUT_SECONDS = 60
AGENT_NAME_CHARS = 28
NOT_AGENT_CHARS = re.compile(r"[^a-z0-9_-]+")
VALID_BRANCH = re.compile(r"^(?!/)(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,120}(?<![/.])$")

Runner = Callable[..., subprocess.CompletedProcess[str]]


class LaunchError(RuntimeError):
    pass


@dataclass(frozen=True)
class Checkout:
    path: str
    branch: str
    is_main: bool
    workspace_id: str = ""


@dataclass(frozen=True)
class Project:
    root: str
    name: str
    main_workspace_id: str
    checkouts: list[Checkout]

    def checkout(self, *, path: str) -> Checkout | None:
        return next((item for item in self.checkouts if item.path == path), None)


@dataclass(frozen=True)
class Launched:
    pane_id: str
    agent: str
    path: str


def _herdr(*, args: list[str], runner: Runner) -> dict[str, Any]:
    try:
        result = runner(
            ["herdr", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=HERDR_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise LaunchError("herdr is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise LaunchError(f"herdr {args[0]} {args[1]} timed out; please try again") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise LaunchError(f"herdr {' '.join(args[:2])} failed: {detail}")
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise LaunchError(f"herdr {' '.join(args[:2])} returned invalid JSON") from exc
    return payload if isinstance(payload, dict) else {}


def _walk(*, node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(node=value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(node=value)


def new_pane_id(*, payload: dict[str, Any]) -> str:
    result = payload.get("result", payload)
    for key in ("root_pane", "pane"):
        found = result.get(key) if isinstance(result, dict) else None
        if isinstance(found, dict) and found.get("pane_id"):
            return str(found["pane_id"])
    for node in _walk(node=result):
        if node.get("pane_id"):
            return str(node["pane_id"])
    raise LaunchError("herdr did not report the new pane")


def read_project(*, root: str, runner: Runner = run) -> Project:
    payload = _herdr(args=["worktree", "list", "--cwd", root], runner=runner)
    result = payload.get("result") or {}
    source = result.get("source") or {}
    repo_root = str(source.get("repo_root") or root)
    checkouts = [
        Checkout(
            path=str(item.get("path", "")),
            branch=str(item.get("branch", "")),
            is_main=not item.get("is_linked_worktree", False),
            workspace_id=str(item.get("open_workspace_id", "")),
        )
        for item in result.get("worktrees") or []
        if isinstance(item, dict) and item.get("path") and not item.get("is_prunable")
    ]
    return Project(
        root=repo_root,
        name=str(source.get("repo_name") or repo_root.rsplit("/", 1)[-1]),
        main_workspace_id=str(source.get("source_workspace_id", "")),
        checkouts=checkouts,
    )


def agent_name(*, hint: str) -> str:
    slug = NOT_AGENT_CHARS.sub("-", hint.lower()).strip("-_")
    slug = slug if slug[:1].isalpha() else f"s-{slug}"
    return f"{slug[:AGENT_NAME_CHARS].rstrip('-_')}-{secrets.token_hex(2)}"


def is_valid_branch(*, branch: str) -> bool:
    return VALID_BRANCH.match(branch) is not None


def _tab_in(*, workspace_id: str, path: str, runner: Runner) -> str:
    payload = _herdr(
        args=["tab", "create", "--workspace", workspace_id, "--cwd", path, "--no-focus"],
        runner=runner,
    )
    return new_pane_id(payload=payload)


def _pane_for(*, project: Project, path: str, runner: Runner) -> str:
    checkout = project.checkout(path=path)
    if checkout is None:
        raise LaunchError(f"{path} is not a checkout of {project.name}")
    workspace_id = project.main_workspace_id if checkout.is_main else checkout.workspace_id
    if workspace_id:
        return _tab_in(workspace_id=workspace_id, path=path, runner=runner)
    if checkout.is_main:
        payload = _herdr(args=["workspace", "create", "--cwd", path, "--no-focus"], runner=runner)
    else:
        payload = _herdr(
            args=["worktree", "open", "--cwd", project.root, "--path", path, "--no-focus"],
            runner=runner,
        )
    return new_pane_id(payload=payload)


def _start(*, pane_id: str, hint: str, resume: str, runner: Runner) -> str:
    name = agent_name(hint=hint)
    args = ["agent", "start", name, "--kind", "claude", "--pane", pane_id]
    if resume:
        args += ["--", "--resume", resume]
    _herdr(args=args, runner=runner)
    return name


def open_session(
    *,
    project: Project,
    path: str,
    resume: str = "",
    runner: Runner = run,
) -> Launched:
    pane_id = _pane_for(project=project, path=path, runner=runner)
    hint = path.rstrip("/").rsplit("/", 1)[-1]
    return Launched(
        pane_id=pane_id,
        agent=_start(pane_id=pane_id, hint=hint, resume=resume, runner=runner),
        path=path,
    )


def create_worktree(*, project: Project, branch: str, runner: Runner = run) -> Launched:
    if not is_valid_branch(branch=branch):
        raise LaunchError(f"{branch!r} is not a usable branch name")
    payload = _herdr(
        args=["worktree", "create", "--cwd", project.root, "--branch", branch, "--no-focus"],
        runner=runner,
    )
    pane_id = new_pane_id(payload=payload)
    hint = branch.rsplit("/", 1)[-1]
    return Launched(
        pane_id=pane_id,
        agent=_start(pane_id=pane_id, hint=hint, resume="", runner=runner),
        path=next(
            (str(node["path"]) for node in _walk(node=payload) if node.get("path")),
            "",
        ),
    )
