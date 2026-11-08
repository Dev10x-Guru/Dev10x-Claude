from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from dev10x.comm.overwatch.delivery import deliver_prompt
from dev10x.comm.overwatch.paths import state_dir
from dev10x.comm.overwatch.probes import (
    ProbeError,
    get_board,
    get_claude_sessions,
    get_herdr_panes,
    submit_prompt,
)
from dev10x.comm.overwatch.sessions import ClaudeSession, HerdrPane, ProbeParseError
from dev10x.comm.skills.bus.maildir import SessionStatus

log = logging.getLogger(__name__)

RELAY_AGENT = "relay"
REARM_PROMPT = "/dev10x:overwatch relay"
READY_STATES = ("idle", "done")
CONFIRMED_BY = "daemon-boot"
BACKOFF_AFTER = 12
MAX_DOUBLINGS = 64
MAX_INTERVAL = 300.0


class RearmOutcome(StrEnum):
    WAITING = "waiting"
    WATCHING = "watching"
    SENT = "sent"


class PromptSender(Protocol):
    def __call__(self, *, pane_id: str, text: str) -> None: ...


class BoardReader(Protocol):
    def __call__(self, *, bus_root: Path) -> list[SessionStatus]: ...


def session_of(*, pane: HerdrPane, sessions: list[ClaudeSession]) -> ClaudeSession | None:
    return next((item for item in sessions if item.session_id == pane.session_id), None)


def looks_like_relay(
    *,
    pane: HerdrPane,
    sessions: list[ClaudeSession],
    mailbox: str,
    cwd: str,
) -> bool:
    session = session_of(pane=pane, sessions=sessions)
    return session is not None and (session.name == mailbox or session.cwd == cwd)


def find_relay(
    *,
    panes: list[HerdrPane],
    sessions: list[ClaudeSession],
    name: str,
    mailbox: str,
    cwd: str,
) -> list[HerdrPane]:
    return [
        pane
        for pane in panes
        if pane.name == name
        and pane.pane_id
        and looks_like_relay(pane=pane, sessions=sessions, mailbox=mailbox, cwd=cwd)
    ]


def relay_is_watching(
    *,
    relay: HerdrPane,
    sessions: list[ClaudeSession],
    board: list[SessionStatus],
    mailbox: str,
) -> bool:
    session = session_of(pane=relay, sessions=sessions)
    line = next((status for status in board if status.mailbox == mailbox), None)
    if session is None or session.started_at is None or line is None:
        return False
    return line.state != "done" and line.updated >= session.started_at


def backoff_delay(
    *,
    interval: float,
    waits: int,
    backoff_after: int = BACKOFF_AFTER,
    max_interval: float = MAX_INTERVAL,
) -> float:
    doublings = min(max(0, waits - backoff_after), MAX_DOUBLINGS)
    return min(interval * 2**doublings, max_interval)


@dataclass
class RelayRearm:
    bus_root: Path
    log_path: Path
    relay_mailbox: str
    agent_name: str = RELAY_AGENT
    relay_cwd: str = field(default_factory=lambda: str(state_dir()))
    herdr_reader: Callable[[], list[HerdrPane]] = get_herdr_panes
    claude_reader: Callable[[], list[ClaudeSession]] = get_claude_sessions
    prompt_sender: PromptSender = submit_prompt
    board_reader: BoardReader = get_board

    def attempt(self) -> RearmOutcome:
        sessions = self.claude_reader()
        matches = find_relay(
            panes=self.herdr_reader(),
            sessions=sessions,
            name=self.agent_name,
            mailbox=self.relay_mailbox,
            cwd=self.relay_cwd,
        )
        if len(matches) > 1:
            log.warning(
                "overwatch relay re-arm: %d panes look like the relay %r, sending to none: %s",
                len(matches),
                self.agent_name,
                ", ".join(pane.pane_id for pane in matches),
            )
            return RearmOutcome.WAITING
        if not matches or matches[0].agent_status not in READY_STATES:
            return RearmOutcome.WAITING
        relay = matches[0]
        if relay_is_watching(
            relay=relay,
            sessions=sessions,
            board=self.board_reader(bus_root=self.bus_root),
            mailbox=self.relay_mailbox,
        ):
            return RearmOutcome.WATCHING
        deliver_prompt(
            pane_id=relay.pane_id,
            text=REARM_PROMPT,
            confirmed_by=CONFIRMED_BY,
            log_path=self.log_path,
            sender=self.prompt_sender,
        )
        return RearmOutcome.SENT


def run_rearm(
    *,
    attempt: Callable[[], RearmOutcome],
    interval: float,
    stop: threading.Event,
    max_interval: float = MAX_INTERVAL,
) -> RearmOutcome | None:
    waits = 0
    while not stop.is_set():
        try:
            outcome = attempt()
        except (ProbeError, ProbeParseError, OSError) as exc:
            log.warning("overwatch relay re-arm attempt failed: %s", exc)
            outcome = RearmOutcome.WAITING
        except Exception:
            log.exception("overwatch relay re-arm attempt failed unexpectedly")
            outcome = RearmOutcome.WAITING
        if outcome != RearmOutcome.WAITING:
            log.info("overwatch relay re-arm: %s", outcome)
            return outcome
        waits += 1
        stop.wait(backoff_delay(interval=interval, waits=waits, max_interval=max_interval))
    return None
