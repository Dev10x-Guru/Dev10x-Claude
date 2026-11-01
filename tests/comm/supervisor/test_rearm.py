"""Tests for re-arming the relay once per supervisor boot."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from dev10x.comm.skills.bus.maildir import SessionStatus, write_status
from dev10x.comm.supervisor.probes import ProbeError
from dev10x.comm.supervisor.rearm import (
    CONFIRMED_BY,
    REARM_PROMPT,
    RearmOutcome,
    RelayRearm,
    find_relay,
    relay_is_watching,
    run_rearm,
)
from dev10x.comm.supervisor.sessions import ClaudeSession, HerdrPane
from tests.comm.supervisor.conftest import NOW

RELAY_ID = "6a1e0c4b-2d7f-4c1e-9b0a-3f5e8d2c7a10"
MAILBOX = "supervisor-relay"


def _pane(*, name: str = "relay", status: str = "idle", pane_id: str = "w7:p1") -> HerdrPane:
    return HerdrPane(
        session_id=RELAY_ID,
        pane_id=pane_id,
        agent_status=status,
        terminal_title="supervisor relay",
        name=name,
    )


def _session(*, started_at: Any = NOW) -> ClaudeSession:
    return ClaudeSession(
        session_id=RELAY_ID,
        pid=1,
        name=MAILBOX,
        cwd="/home/janusz/.config/Dev10x/supervisor",
        status="idle",
        waiting_for="",
        started_at=started_at,
    )


def _line(*, offset: timedelta, state: str = "working") -> SessionStatus:
    return SessionStatus(
        mailbox=MAILBOX,
        state=state,
        summary="Relaying answers.",
        updated=NOW + offset,
        callsign="answer relay",
    )


class RecordingSender:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


class TestFindRelay:
    def test_matches_by_name(self) -> None:
        relay = _pane()

        assert find_relay(panes=[_pane(name="other"), relay], name="relay") == relay

    @pytest.mark.parametrize(
        "pane",
        [_pane(name="supervisor-relay"), _pane(pane_id="")],
        ids=["other-name", "no-pane"],
    )
    def test_ignores_non_matching(self, pane: HerdrPane) -> None:
        assert find_relay(panes=[pane], name="relay") is None


class TestRelayIsWatching:
    @pytest.mark.parametrize(
        ("sessions", "board", "watching"),
        [
            ([_session()], [_line(offset=timedelta(seconds=30))], True),
            ([_session()], [_line(offset=timedelta(0))], True),
            ([_session()], [_line(offset=-timedelta(hours=2))], False),
            ([_session()], [_line(offset=timedelta(seconds=30), state="done")], False),
            ([_session()], [], False),
            ([], [_line(offset=timedelta(seconds=30))], False),
            ([_session(started_at=None)], [_line(offset=timedelta(seconds=30))], False),
        ],
        ids=[
            "armed-after-start",
            "armed-at-start",
            "line-from-before-restart",
            "line-says-done",
            "no-line",
            "session-not-listed",
            "start-unknown",
        ],
    )
    def test_watching(
        self,
        sessions: list[ClaudeSession],
        board: list[SessionStatus],
        watching: bool,
    ) -> None:
        assert (
            relay_is_watching(relay=_pane(), sessions=sessions, board=board, mailbox=MAILBOX)
            is watching
        )


@pytest.fixture
def log_path(tmp_path: Path) -> Path:
    return tmp_path / "actions.jsonl"


@pytest.fixture
def bus_root(tmp_path: Path) -> Path:
    return tmp_path / "bus"


@pytest.fixture
def sender() -> RecordingSender:
    return RecordingSender()


@pytest.fixture
def make_rearm(
    bus_root: Path,
    log_path: Path,
    sender: RecordingSender,
) -> Callable[..., RelayRearm]:
    def make(*, panes: list[HerdrPane]) -> RelayRearm:
        return RelayRearm(
            bus_root=bus_root,
            log_path=log_path,
            relay_mailbox=MAILBOX,
            herdr_reader=lambda: panes,
            claude_reader=lambda: [_session()],
            prompt_sender=sender,
        )

    return make


class TestAttempt:
    @pytest.mark.parametrize(
        "panes",
        [[], [_pane(status="working")], [_pane(status="blocked")]],
        ids=["absent", "working", "blocked"],
    )
    def test_waits_until_relay_is_ready(
        self,
        make_rearm: Callable[..., RelayRearm],
        sender: RecordingSender,
        panes: list[HerdrPane],
    ) -> None:
        assert (make_rearm(panes=panes).attempt(), sender.calls) == (RearmOutcome.WAITING, [])

    def test_skips_a_relay_already_watching(
        self,
        make_rearm: Callable[..., RelayRearm],
        sender: RecordingSender,
        bus_root: Path,
        log_path: Path,
    ) -> None:
        write_status(root=bus_root, status=_line(offset=timedelta(minutes=1)))

        outcome = make_rearm(panes=[_pane()]).attempt()

        assert (outcome, sender.calls, log_path.exists()) == (RearmOutcome.WATCHING, [], False)

    @pytest.mark.parametrize("status", ["idle", "done"])
    def test_prompts_a_resumed_relay_and_logs_it(
        self,
        make_rearm: Callable[..., RelayRearm],
        sender: RecordingSender,
        bus_root: Path,
        log_path: Path,
        status: str,
    ) -> None:
        write_status(root=bus_root, status=_line(offset=-timedelta(hours=3)))

        outcome = make_rearm(panes=[_pane(status=status)]).attempt()
        record = json.loads(log_path.read_text(encoding="utf-8"))

        assert (outcome, sender.calls, record["action"], record["detail"], record["target"]) == (
            RearmOutcome.SENT,
            [{"pane_id": "w7:p1", "text": REARM_PROMPT}],
            "prompt",
            REARM_PROMPT,
            "w7:p1",
        )

    def test_logs_who_confirmed(
        self,
        make_rearm: Callable[..., RelayRearm],
        log_path: Path,
    ) -> None:
        make_rearm(panes=[_pane()]).attempt()

        assert json.loads(log_path.read_text(encoding="utf-8"))["confirmed_by"] == CONFIRMED_BY


class TestRunRearm:
    def test_retries_until_an_outcome(self) -> None:
        outcomes = iter([RearmOutcome.WAITING, RearmOutcome.SENT, RearmOutcome.SENT])
        calls: list[int] = []

        def attempt() -> RearmOutcome:
            calls.append(1)
            return next(outcomes)

        result = run_rearm(attempt=attempt, interval=0, stop=threading.Event())

        assert (result, len(calls)) == (RearmOutcome.SENT, 2)

    @pytest.mark.parametrize(
        "error",
        [ProbeError("herdr is not installed"), OSError("board unreadable")],
        ids=["probe", "os"],
    )
    def test_a_failed_attempt_is_retried(self, error: Exception) -> None:
        attempt = Mock(side_effect=[error, RearmOutcome.WATCHING])

        result = run_rearm(attempt=attempt, interval=0, stop=threading.Event())

        assert (result, attempt.call_count) == (RearmOutcome.WATCHING, 2)

    def test_stops_with_the_daemon(self) -> None:
        stop = threading.Event()

        def attempt() -> RearmOutcome:
            stop.set()
            return RearmOutcome.WAITING

        assert run_rearm(attempt=attempt, interval=60, stop=stop) is None
