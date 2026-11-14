"""Tests for re-arming the relay once per Overwatch boot."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from dev10x.comm.overwatch.probes import ProbeError
from dev10x.comm.overwatch.rearm import (
    BACKOFF_AFTER,
    CONFIRMED_BY,
    MAX_INTERVAL,
    REARM_PROMPT,
    RearmOutcome,
    RelayRearm,
    backoff_delay,
    find_relay,
    relay_is_watching,
    run_rearm,
)
from dev10x.comm.overwatch.sessions import ClaudeSession, HerdrPane, ProbeParseError
from dev10x.comm.skills.bus.maildir import SessionStatus, write_status
from tests.comm.overwatch.conftest import NOW, RecordingSender

RELAY_ID = "6a1e0c4b-2d7f-4c1e-9b0a-3f5e8d2c7a10"
OTHER_ID = "0b9d8c7e-6f5a-4b3c-8d2e-1f0a9b8c7d6e"
MAILBOX = "overwatch-relay"
RELAY_CWD = "/home/janusz/.config/Dev10x/overwatch"


def _pane(
    *,
    name: str = "relay",
    status: str = "idle",
    pane_id: str = "w7:p1",
    session_id: str = RELAY_ID,
) -> HerdrPane:
    return HerdrPane(
        session_id=session_id,
        pane_id=pane_id,
        agent_status=status,
        terminal_title="overwatch relay",
        name=name,
    )


def _session(
    *,
    started_at: Any = NOW,
    name: str = MAILBOX,
    cwd: str = RELAY_CWD,
    session_id: str = RELAY_ID,
) -> ClaudeSession:
    return ClaudeSession(
        session_id=session_id,
        pid=1,
        name=name,
        cwd=cwd,
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


def _find(*, panes: list[HerdrPane], sessions: list[ClaudeSession]) -> list[HerdrPane]:
    return find_relay(panes=panes, sessions=sessions, name="relay", mailbox=MAILBOX, cwd=RELAY_CWD)


class TestFindRelay:
    @pytest.mark.parametrize(
        "session",
        [_session(), _session(name="kb-84"), _session(cwd="/work/elsewhere")],
        ids=["mailbox-and-cwd", "cwd-only", "mailbox-only"],
    )
    def test_matches_a_named_pane_whose_session_looks_like_the_relay(
        self, session: ClaudeSession
    ) -> None:
        relay = _pane()

        assert _find(panes=[_pane(name="other"), relay], sessions=[session]) == [relay]

    @pytest.mark.parametrize(
        ("pane", "sessions"),
        [
            (_pane(name="overwatch-relay"), [_session()]),
            (_pane(pane_id=""), [_session()]),
            (_pane(), [_session(name="kb-84", cwd="/work/elsewhere")]),
            (_pane(), [_session(session_id=OTHER_ID)]),
            (_pane(), []),
        ],
        ids=["other-name", "no-pane", "foreign-session", "session-not-listed", "no-sessions"],
    )
    def test_ignores_non_matching(self, pane: HerdrPane, sessions: list[ClaudeSession]) -> None:
        assert _find(panes=[pane], sessions=sessions) == []

    @pytest.mark.parametrize(
        "spelling",
        [RELAY_CWD + "/", RELAY_CWD + "/./", "/home/janusz/.config/Dev10x/../Dev10x/overwatch"],
        ids=["trailing-slash", "dot-segment", "parent-segment"],
    )
    def test_matches_the_state_dir_however_it_is_spelled(self, spelling: str) -> None:
        relay = _pane()

        assert _find(panes=[relay], sessions=[_session(name="kb-84", cwd=spelling)]) == [relay]

    def test_matches_the_state_dir_through_a_symlink(self, tmp_path: Path) -> None:
        state = tmp_path / "overwatch"
        state.mkdir()
        link = tmp_path / "config-link"
        link.symlink_to(tmp_path)
        relay = _pane()

        matches = find_relay(
            panes=[relay],
            sessions=[_session(name="kb-84", cwd=str(link / "overwatch"))],
            name="relay",
            mailbox=MAILBOX,
            cwd=str(state),
        )

        assert matches == [relay]

    def test_an_empty_session_cwd_is_not_the_state_dir(self) -> None:
        assert _find(panes=[_pane()], sessions=[_session(name="kb-84", cwd="")]) == []

    def test_reports_every_pane_that_matches(self) -> None:
        first = _pane()
        second = _pane(pane_id="w8:p1", session_id=OTHER_ID)

        matches = _find(
            panes=[first, second],
            sessions=[_session(), _session(session_id=OTHER_ID)],
        )

        assert matches == [first, second]


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
    def make(*, panes: list[HerdrPane], sessions: list[ClaudeSession] | None = None) -> RelayRearm:
        return RelayRearm(
            bus_root=bus_root,
            log_path=log_path,
            relay_mailbox=MAILBOX,
            relay_cwd=RELAY_CWD,
            herdr_reader=lambda: panes,
            claude_reader=lambda: [_session()] if sessions is None else sessions,
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

    def test_waits_when_the_named_pane_is_not_the_relay(
        self,
        make_rearm: Callable[..., RelayRearm],
        sender: RecordingSender,
    ) -> None:
        rearm = make_rearm(
            panes=[_pane()], sessions=[_session(name="kb-84", cwd="/work/elsewhere")]
        )

        assert (rearm.attempt(), sender.calls) == (RearmOutcome.WAITING, [])

    def test_waits_and_warns_when_more_than_one_pane_matches(
        self,
        make_rearm: Callable[..., RelayRearm],
        sender: RecordingSender,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        rearm = make_rearm(
            panes=[_pane(), _pane(pane_id="w8:p1", session_id=OTHER_ID)],
            sessions=[_session(), _session(session_id=OTHER_ID)],
        )

        with caplog.at_level(logging.WARNING, logger="dev10x.comm.overwatch.rearm"):
            outcome = rearm.attempt()

        assert (outcome, sender.calls, "w7:p1, w8:p1" in caplog.text) == (
            RearmOutcome.WAITING,
            [],
            True,
        )

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

    def test_a_failed_log_still_counts_as_sent(
        self,
        make_rearm: Callable[..., RelayRearm],
        sender: RecordingSender,
        unwritable_log_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        rearm = make_rearm(panes=[_pane()])
        rearm.log_path = unwritable_log_path

        with caplog.at_level(logging.WARNING, logger="dev10x.comm.overwatch.delivery"):
            outcome = rearm.attempt()

        assert (outcome, sender.calls, "could not record" in caplog.text) == (
            RearmOutcome.SENT,
            [{"pane_id": "w7:p1", "text": REARM_PROMPT}],
            True,
        )

    def test_logs_who_confirmed(
        self,
        make_rearm: Callable[..., RelayRearm],
        log_path: Path,
    ) -> None:
        make_rearm(panes=[_pane()]).attempt()

        assert json.loads(log_path.read_text(encoding="utf-8"))["confirmed_by"] == CONFIRMED_BY

    def test_defaults_to_the_overwatch_state_dir(self, config_home: Path, tmp_path: Path) -> None:
        rearm = RelayRearm(bus_root=tmp_path, log_path=tmp_path / "log", relay_mailbox=MAILBOX)

        assert rearm.relay_cwd == str(config_home / "overwatch")


class TestBackoffDelay:
    @pytest.mark.parametrize(
        ("waits", "delay"),
        [
            (1, 5.0),
            (BACKOFF_AFTER, 5.0),
            (BACKOFF_AFTER + 1, 10.0),
            (BACKOFF_AFTER + 3, 40.0),
            (BACKOFF_AFTER + 20, MAX_INTERVAL),
            (BACKOFF_AFTER + 1_000_000, MAX_INTERVAL),
        ],
        ids=["first", "last-fast", "doubled", "tripled", "capped", "days-of-waiting"],
    )
    def test_keeps_the_interval_then_doubles_up_to_the_cap(self, waits: int, delay: float) -> None:
        assert backoff_delay(interval=5.0, waits=waits) == delay


class RecordingStop(threading.Event):
    def __init__(self, *, give_up_after: int) -> None:
        super().__init__()
        self.give_up_after = give_up_after
        self.delays: list[float | None] = []

    def wait(self, timeout: float | None = None) -> bool:
        self.delays.append(timeout)
        if len(self.delays) >= self.give_up_after:
            self.set()
        return self.is_set()


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
        [
            ProbeError("herdr is not installed"),
            ProbeParseError("herdr returned invalid JSON"),
            OSError("board unreadable"),
            TypeError("can't compare offset-naive and offset-aware datetimes"),
        ],
        ids=["probe", "parse", "os", "unexpected"],
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

    def test_backs_off_while_the_relay_stays_absent(self) -> None:
        stop = RecordingStop(give_up_after=BACKOFF_AFTER + 3)

        result = run_rearm(
            attempt=lambda: RearmOutcome.WAITING, interval=5.0, stop=stop, max_interval=30.0
        )

        assert (result, stop.delays[: BACKOFF_AFTER - 1], stop.delays[BACKOFF_AFTER - 1 :]) == (
            None,
            [5.0] * (BACKOFF_AFTER - 1),
            [5.0, 10.0, 20.0, 30.0],
        )
