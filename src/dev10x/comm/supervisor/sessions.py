from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from dev10x.comm.skills.bus.maildir import SessionStatus

GROUPS = ("needs-you", "working", "done")


class ProbeParseError(ValueError):
    pass


@dataclass(frozen=True)
class ClaudeSession:
    session_id: str
    pid: int
    name: str
    cwd: str
    status: str
    waiting_for: str
    started_at: datetime | None = None


@dataclass(frozen=True)
class HerdrPane:
    session_id: str
    pane_id: str
    agent_status: str
    terminal_title: str
    name: str = ""


@dataclass(frozen=True)
class SessionView:
    session_id: str
    name: str
    cwd: str
    status: str
    waiting_for: str
    pane_id: str
    callsign: str
    summary: str
    board_state: str
    group: str


def _load(*, raw: str, source: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProbeParseError(f"{source} returned invalid JSON: {exc}") from exc


def _started_at(*, raw: object) -> datetime | None:
    if not isinstance(raw, int | float) or isinstance(raw, bool):
        return None
    return datetime.fromtimestamp(raw / 1000, tz=UTC)


def parse_claude_agents(raw: str) -> list[ClaudeSession]:
    entries = _load(raw=raw, source="claude agents")
    if not isinstance(entries, list):
        raise ProbeParseError("claude agents returned a non-list payload")
    return [
        ClaudeSession(
            session_id=str(entry["sessionId"]),
            pid=int(entry.get("pid", 0)),
            name=str(entry.get("name", "")),
            cwd=str(entry.get("cwd", "")),
            status=str(entry.get("status", "")),
            waiting_for=str(entry.get("waitingFor", "")),
            started_at=_started_at(raw=entry.get("startedAt")),
        )
        for entry in entries
        if isinstance(entry, dict) and entry.get("sessionId")
    ]


def parse_herdr_agents(raw: str) -> list[HerdrPane]:
    payload = _load(raw=raw, source="herdr agent list")
    try:
        agents = payload["result"]["agents"]
    except (KeyError, TypeError) as exc:
        raise ProbeParseError("herdr agent list returned no result.agents") from exc
    return [
        HerdrPane(
            session_id=str(agent["agent_session"]["value"]),
            pane_id=str(agent.get("pane_id", "")),
            agent_status=str(agent.get("agent_status", "")),
            terminal_title=str(agent.get("terminal_title", "")),
            name=str(agent.get("name", "")),
        )
        for agent in agents
        if agent.get("agent") == "claude" and (agent.get("agent_session") or {}).get("value")
    ]


def _group(*, status: str, board_state: str) -> str:
    if status == "waiting" or board_state == "needs-input":
        return "needs-you"
    if status == "busy" or board_state == "working":
        return "working"
    return "done"


def merge_sessions(
    *,
    claude: list[ClaudeSession],
    panes: list[HerdrPane],
    board: list[SessionStatus],
) -> list[SessionView]:
    pane_by_session = {pane.session_id: pane.pane_id for pane in panes}
    board_by_mailbox = {status.mailbox: status for status in board}
    views = []
    for session in claude:
        line = board_by_mailbox.get(session.name)
        board_state = line.state if line else ""
        views.append(
            SessionView(
                session_id=session.session_id,
                name=session.name,
                cwd=session.cwd,
                status=session.status,
                waiting_for=session.waiting_for,
                pane_id=pane_by_session.get(session.session_id, ""),
                callsign=line.callsign if line else "",
                summary=line.summary if line else "",
                board_state=board_state,
                group=_group(status=session.status, board_state=board_state),
            )
        )
    return sorted(views, key=lambda view: (GROUPS.index(view.group), view.name))
