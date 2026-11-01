from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from dev10x.comm.skills.bus.maildir import SessionStatus
from dev10x.comm.supervisor.delivery import deliver_prompt
from dev10x.comm.supervisor.probes import (
    ProbeError,
    get_board,
    get_claude_sessions,
    get_herdr_panes,
    submit_prompt,
)
from dev10x.comm.supervisor.sessions import ClaudeSession, HerdrPane, ProbeParseError

log = logging.getLogger(__name__)

RELAY_AGENT = "relay"
REARM_PROMPT = "/dev10x:supervisor relay"
READY_STATES = ("idle", "done")
CONFIRMED_BY = "daemon-boot"


class RearmOutcome(StrEnum):
    WAITING = "waiting"
    WATCHING = "watching"
    SENT = "sent"


def find_relay(*, panes: list[HerdrPane], name: str) -> HerdrPane | None:
    return next((pane for pane in panes if pane.name == name and pane.pane_id), None)


def relay_is_watching(
    *,
    relay: HerdrPane,
    sessions: list[ClaudeSession],
    board: list[SessionStatus],
    mailbox: str,
) -> bool:
    session = next((item for item in sessions if item.session_id == relay.session_id), None)
    line = next((status for status in board if status.mailbox == mailbox), None)
    if session is None or session.started_at is None or line is None:
        return False
    return line.state != "done" and line.updated >= session.started_at


@dataclass
class RelayRearm:
    bus_root: Path
    log_path: Path
    relay_mailbox: str
    agent_name: str = RELAY_AGENT
    herdr_reader: Callable[[], list[HerdrPane]] = get_herdr_panes
    claude_reader: Callable[[], list[ClaudeSession]] = get_claude_sessions
    prompt_sender: Callable[..., None] = submit_prompt
    board_reader: Callable[..., list[SessionStatus]] = get_board

    def attempt(self) -> RearmOutcome:
        relay = find_relay(panes=self.herdr_reader(), name=self.agent_name)
        if relay is None or relay.agent_status not in READY_STATES:
            return RearmOutcome.WAITING
        if relay_is_watching(
            relay=relay,
            sessions=self.claude_reader(),
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
) -> RearmOutcome | None:
    while not stop.is_set():
        try:
            outcome = attempt()
        except (ProbeError, ProbeParseError, OSError) as exc:
            log.warning("supervisor relay re-arm attempt failed: %s", exc)
            outcome = RearmOutcome.WAITING
        if outcome != RearmOutcome.WAITING:
            log.info("supervisor relay re-arm: %s", outcome)
            return outcome
        stop.wait(interval)
    return None
