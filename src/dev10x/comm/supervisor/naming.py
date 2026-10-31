from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePath

from dev10x.comm.supervisor.sessions import SessionView
from dev10x.comm.supervisor.workspace import Workspace

MAX_NAME_CHARS = 64
VALID_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
NOT_A_NAME = re.compile(r"[^A-Za-z0-9._-]+")
UNNAMED_BRANCHES = frozenset({"", "HEAD", "main", "master", "develop", "development", "trunk"})


@dataclass(frozen=True)
class Rename:
    session: SessionView
    name: str


def is_default_name(*, name: str, cwd: str) -> bool:
    folder = re.escape(PurePath(cwd).name)
    return bool(folder) and re.fullmatch(rf"{folder}-[0-9a-f]{{2}}", name) is not None


def name_from_branch(*, branch: str) -> str:
    if branch in UNNAMED_BRANCHES:
        return ""
    parts = branch.split("/")
    if len(parts) >= 4:
        kept = [parts[1], *parts[3:]]
    else:
        kept = parts[1:] if len(parts) > 1 else parts
    return NOT_A_NAME.sub("-", "-".join(kept)).strip("-.")[:MAX_NAME_CHARS].rstrip("-.")


def is_valid_name(*, name: str) -> bool:
    return VALID_NAME.match(name) is not None


def plan_renames(
    *,
    sessions: list[SessionView],
    workspaces: dict[str, Workspace],
) -> list[Rename]:
    taken = {view.name for view in sessions}
    plan = []
    for view in sessions:
        if view.status != "idle" or not view.pane_id:
            continue
        if not is_default_name(name=view.name, cwd=view.cwd):
            continue
        workspace = workspaces.get(view.cwd)
        name = name_from_branch(branch=workspace.branch if workspace else "")
        if not name or name in taken:
            continue
        taken.add(name)
        plan.append(Rename(session=view, name=name))
    return plan
