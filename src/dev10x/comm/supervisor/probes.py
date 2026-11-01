from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from dev10x.comm.skills.bus.maildir import SessionStatus, parse_status, status_files
from dev10x.comm.supervisor.sessions import (
    ClaudeSession,
    HerdrPane,
    ProbeParseError,
    SessionView,
    merge_sessions,
    parse_claude_agents,
    parse_herdr_agents,
)
from dev10x.subprocess_utils import run

PROBE_TIMEOUT_SECONDS = 10
PANE_LINES = 60
CLAUDE_AGENTS = ["claude", "agents", "--json"]
HERDR_AGENTS = ["herdr", "agent", "list"]

Runner = Callable[..., subprocess.CompletedProcess[str]]


class ProbeError(RuntimeError):
    pass


@dataclass(frozen=True)
class Snapshot:
    sessions: list[SessionView]
    errors: dict[str, str] = field(default_factory=dict)
    taken_at: datetime = field(default_factory=lambda: datetime.now().astimezone())


def _call(*, args: list[str], runner: Runner) -> str:
    try:
        result = runner(
            args,
            capture_output=True,
            text=True,
            check=False,
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise ProbeError(f"{args[0]} is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise ProbeError(f"{' '.join(args)} timed out after {PROBE_TIMEOUT_SECONDS}s") from exc
    if result.returncode != 0:
        raise ProbeError(f"{' '.join(args)} exited {result.returncode}: {result.stderr.strip()}")
    return result.stdout


def get_board(*, bus_root: Path) -> list[SessionStatus]:
    statuses = [parse_status(path=path) for path in status_files(root=bus_root)]
    return [status for status in statuses if status is not None]


def get_claude_sessions(*, runner: Runner = run) -> list[ClaudeSession]:
    return parse_claude_agents(raw=_call(args=CLAUDE_AGENTS, runner=runner))


def get_herdr_panes(*, runner: Runner = run) -> list[HerdrPane]:
    return parse_herdr_agents(raw=_call(args=HERDR_AGENTS, runner=runner))


def take_snapshot(*, bus_root: Path, runner: Runner = run) -> Snapshot:
    errors: dict[str, str] = {}
    claude = []
    panes = []
    try:
        claude = get_claude_sessions(runner=runner)
    except (ProbeError, ProbeParseError) as exc:
        errors["claude"] = str(exc)
    try:
        panes = get_herdr_panes(runner=runner)
    except (ProbeError, ProbeParseError) as exc:
        errors["herdr"] = str(exc)
    try:
        board = get_board(bus_root=bus_root)
    except OSError as exc:
        errors["bus"] = str(exc)
        board = []
    return Snapshot(
        sessions=merge_sessions(claude=claude, panes=panes, board=board),
        errors=errors,
    )


def read_pane(
    *,
    pane_id: str,
    lines: int = PANE_LINES,
    source: str = "visible",
    ansi: bool = False,
    runner: Runner = run,
) -> str:
    args = [
        "herdr",
        "agent",
        "read",
        pane_id,
        "--source",
        source,
        "--lines",
        str(lines),
        "--format",
        "ansi" if ansi else "text",
    ]
    try:
        return _call(args=args, runner=runner)
    except ProbeError:
        return ""


def send_keys(*, pane_id: str, keys: list[str], runner: Runner = run) -> None:
    _call(args=["herdr", "agent", "send-keys", pane_id, *keys], runner=runner)


def submit_prompt(*, pane_id: str, text: str, runner: Runner = run) -> None:
    _call(args=["herdr", "agent", "prompt", pane_id, text], runner=runner)
