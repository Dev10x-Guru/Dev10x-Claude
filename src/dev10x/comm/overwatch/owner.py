"""Find the Claude session that runs `overwatch artifact put` (GH-1938, ADR-0036 D3)."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass

from dev10x.comm.overwatch.probes import ProbeError, Runner, get_claude_sessions
from dev10x.comm.overwatch.sessions import ClaudeSession, ProbeParseError
from dev10x.domain.common.result import Result, err, ok
from dev10x.subprocess_utils import run

MAX_HOPS = 32
PS_TIMEOUT_SECONDS = 5
SESSION_HINT = "pass --session NAME_OR_ID"


@dataclass(frozen=True)
class ArtifactOwner:
    session_id: str
    name: str
    cwd: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _owner(*, session: ClaudeSession) -> ArtifactOwner:
    return ArtifactOwner(session_id=session.session_id, name=session.name, cwd=session.cwd)


def parent_pid(*, pid: int, runner: Runner = run) -> int | None:
    try:
        result = runner(
            ["ps", "-o", "ppid=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
            timeout=PS_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def match_session(*, sessions: list[ClaudeSession], wanted: str) -> Result[ArtifactOwner]:
    matches = [session for session in sessions if wanted in (session.session_id, session.name)]
    if not matches:
        return err(
            f'No running Claude session is named "{wanted}" or has that id; check --session.'
        )
    if len(matches) > 1:
        return err(f'Several sessions are named "{wanted}"; pass --session with the session id.')
    return ok(_owner(session=matches[0]))


def walk_ancestors(
    *,
    sessions: list[ClaudeSession],
    start_pid: int,
    parent_of: Callable[[int], int | None],
) -> Result[ArtifactOwner]:
    by_pid = {session.pid: session for session in sessions if session.pid}
    pid: int | None = start_pid
    for _ in range(MAX_HOPS):
        if pid is None or pid <= 1:
            break
        if pid in by_pid:
            return ok(_owner(session=by_pid[pid]))
        pid = parent_of(pid)
    return err(
        "Could not find the Claude session that ran this among its parent processes; "
        f"{SESSION_HINT}."
    )


def find_owner(
    *,
    start_pid: int,
    session: str = "",
    sessions_reader: Callable[[], list[ClaudeSession]] = get_claude_sessions,
    parent_of: Callable[[int], int | None] = lambda pid: parent_pid(pid=pid),
) -> Result[ArtifactOwner]:
    try:
        sessions = sessions_reader()
    except (ProbeError, ProbeParseError) as exc:
        return err(f"Could not list Claude sessions: {exc}")
    if session:
        return match_session(sessions=sessions, wanted=session)
    return walk_ancestors(sessions=sessions, start_pid=start_pid, parent_of=parent_of)
