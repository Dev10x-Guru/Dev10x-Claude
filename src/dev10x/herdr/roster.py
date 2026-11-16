from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

Role = Literal["main", "worktree", "unbound"]

CLAUDE_AGENT = "claude"


class RosterParseError(ValueError):
    pass


@dataclass(frozen=True)
class Workspace:
    workspace_id: str
    label: str
    number: int
    checkout_path: str = ""
    repo_key: str = ""
    repo_name: str = ""
    repo_root: str = ""
    is_linked_worktree: bool = False

    @property
    def role(self) -> Role:
        if not self.repo_key:
            return "unbound"
        return "worktree" if self.is_linked_worktree else "main"


@dataclass(frozen=True)
class Agent:
    pane_id: str
    workspace_id: str
    kind: str
    status: str
    cwd: str
    name: str = ""
    terminal_title: str = ""


@dataclass(frozen=True)
class Session:
    pane_id: str
    name: str
    status: str
    role: Role
    workspace_id: str
    workspace_label: str
    checkout_path: str
    cwd: str
    terminal_title: str


@dataclass(frozen=True)
class RepoRoster:
    repo_name: str
    repo_key: str
    repo_root: str
    coordinator: Session | None
    main_sessions: list[Session] = field(default_factory=list)
    worktree_sessions: list[Session] = field(default_factory=list)


@dataclass(frozen=True)
class Caller:
    role: Role | Literal["outside"]
    repo_root: str = ""
    workspace_id: str = ""


@dataclass(frozen=True)
class Roster:
    repos: list[RepoRoster]
    unbound: list[Session]
    caller: Caller

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load(*, raw: str, source: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RosterParseError(f"{source} returned invalid JSON: {exc}") from exc


def parse_workspaces(raw: str) -> list[Workspace]:
    payload = _load(raw=raw, source="herdr workspace list")
    try:
        entries = payload["result"]["workspaces"]
    except (KeyError, TypeError) as exc:
        raise RosterParseError("herdr workspace list returned no result.workspaces") from exc
    workspaces = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("workspace_id"):
            continue
        binding = entry.get("worktree") or {}
        workspaces.append(
            Workspace(
                workspace_id=str(entry["workspace_id"]),
                label=str(entry.get("label", "")),
                number=int(entry.get("number", 0)),
                checkout_path=str(binding.get("checkout_path", "")),
                repo_key=str(binding.get("repo_key", "")),
                repo_name=str(binding.get("repo_name", "")),
                repo_root=str(binding.get("repo_root", "")),
                is_linked_worktree=bool(binding.get("is_linked_worktree", False)),
            )
        )
    return workspaces


def parse_agents(raw: str) -> list[Agent]:
    payload = _load(raw=raw, source="herdr agent list")
    try:
        entries = payload["result"]["agents"]
    except (KeyError, TypeError) as exc:
        raise RosterParseError("herdr agent list returned no result.agents") from exc
    return [
        Agent(
            pane_id=str(entry["pane_id"]),
            workspace_id=str(entry.get("workspace_id", "")),
            kind=str(entry.get("agent", "")),
            status=str(entry.get("agent_status", "")),
            cwd=str(entry.get("cwd", "")),
            name=str(entry.get("name", "")),
            terminal_title=str(entry.get("terminal_title_stripped", "")),
        )
        for entry in entries
        if isinstance(entry, dict) and entry.get("pane_id")
    ]


def _session(*, agent: Agent, workspace: Workspace | None) -> Session:
    return Session(
        pane_id=agent.pane_id,
        name=agent.name,
        status=agent.status,
        role=workspace.role if workspace else "unbound",
        workspace_id=agent.workspace_id,
        workspace_label=workspace.label if workspace else "",
        checkout_path=workspace.checkout_path if workspace else "",
        cwd=agent.cwd,
        terminal_title=agent.terminal_title,
    )


def _pick_coordinator(
    *,
    mains: list[Session],
    repo_name: str,
    numbers: dict[str, int],
) -> Session | None:
    if not mains:
        return None
    labelled = [session for session in mains if session.workspace_label == repo_name]
    candidates = labelled or mains
    return min(candidates, key=lambda session: numbers.get(session.workspace_id, 0))


def _locate_caller(*, cwd: str, workspaces: list[Workspace]) -> Caller:
    if not cwd:
        return Caller(role="outside")
    target = Path(cwd)
    bound = [workspace for workspace in workspaces if workspace.checkout_path]
    matches = [
        workspace
        for workspace in bound
        if target == Path(workspace.checkout_path)
        or Path(workspace.checkout_path) in target.parents
    ]
    if not matches:
        return Caller(role="outside")
    closest = max(matches, key=lambda workspace: len(workspace.checkout_path))
    return Caller(
        role=closest.role,
        repo_root=closest.repo_root,
        workspace_id=closest.workspace_id,
    )


def build_roster(
    *,
    workspaces: list[Workspace],
    agents: list[Agent],
    cwd: str = "",
    repo_root: str = "",
    kind: str = CLAUDE_AGENT,
) -> Roster:
    by_id = {workspace.workspace_id: workspace for workspace in workspaces}
    numbers = {workspace.workspace_id: workspace.number for workspace in workspaces}
    grouped: dict[str, list[tuple[Session, Workspace]]] = {}
    unbound: list[Session] = []
    for agent in agents:
        if agent.kind != kind:
            continue
        workspace = by_id.get(agent.workspace_id)
        session = _session(agent=agent, workspace=workspace)
        if workspace is None or session.role == "unbound":
            unbound.append(session)
            continue
        grouped.setdefault(workspace.repo_key, []).append((session, workspace))
    repos = []
    for repo_key, members in sorted(grouped.items(), key=lambda item: item[1][0][1].repo_name):
        sample = members[0][1]
        if repo_root and sample.repo_root != repo_root:
            continue
        mains = [session for session, _ in members if session.role == "main"]
        worktrees = [session for session, _ in members if session.role == "worktree"]
        repos.append(
            RepoRoster(
                repo_name=sample.repo_name,
                repo_key=repo_key,
                repo_root=sample.repo_root,
                coordinator=_pick_coordinator(
                    mains=mains,
                    repo_name=sample.repo_name,
                    numbers=numbers,
                ),
                main_sessions=mains,
                worktree_sessions=worktrees,
            )
        )
    return Roster(
        repos=repos,
        unbound=[] if repo_root else unbound,
        caller=_locate_caller(cwd=cwd, workspaces=workspaces),
    )
