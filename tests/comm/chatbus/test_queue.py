from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import pytest
from dev10x.domain.common.result import ErrorResult, SuccessResult

from dev10x.comm.chatbus.events import to_db_time
from dev10x.comm.chatbus.ingest import ingest_events
from dev10x.comm.chatbus.queue import (
    WorkItem,
    WorkKind,
    WorkStatus,
    ack,
    claim,
    enqueue,
    release,
)
from dev10x.comm.chatbus.store import open_store
from tests.comm.chatbus.factories import NOW, SPACE, message_event

LEASE = timedelta(minutes=5)


def _event_ids(*, conn: sqlite3.Connection, count: int) -> list[int]:
    events = [message_event(number=number) for number in range(1, count + 1)]
    assert isinstance(ingest_events(conn=conn, space=SPACE, events=events, now=NOW), SuccessResult)
    return [row[0] for row in conn.execute("SELECT id FROM events ORDER BY id").fetchall()]


def _enqueue(
    *,
    conn: sqlite3.Connection,
    event_id: int,
    kind: WorkKind = WorkKind.REPLY,
    status: WorkStatus = WorkStatus.QUEUED,
) -> WorkItem:
    result = enqueue(conn=conn, event_id=event_id, kind=kind, now=NOW, status=status)
    assert isinstance(result, SuccessResult)
    return result.value


def _claim(*, conn: sqlite3.Connection, claimer: str, minutes_later: int = 0) -> WorkItem | None:
    result = claim(
        conn=conn,
        claimer=claimer,
        lease=LEASE,
        now=NOW + timedelta(minutes=minutes_later),
    )
    assert isinstance(result, SuccessResult)
    return result.value


@pytest.fixture
def queued(conn: sqlite3.Connection) -> WorkItem:
    (event_id,) = _event_ids(conn=conn, count=1)
    return _enqueue(conn=conn, event_id=event_id)


@pytest.fixture
def claimed(conn: sqlite3.Connection, queued: WorkItem) -> WorkItem:
    item = _claim(conn=conn, claimer="session-a")
    assert item is not None
    return item


class TestEnqueue:
    def test_starts_queued(self, queued: WorkItem) -> None:
        assert (queued.status, queued.kind, queued.attempts) == (
            WorkStatus.QUEUED,
            WorkKind.REPLY,
            0,
        )

    def test_repeat_returns_existing_item(
        self, conn: sqlite3.Connection, queued: WorkItem
    ) -> None:
        assert _enqueue(conn=conn, event_id=queued.event_id) == queued

    def test_other_kind_is_separate_item(self, conn: sqlite3.Connection, queued: WorkItem) -> None:
        other = _enqueue(conn=conn, event_id=queued.event_id, kind=WorkKind.PRIVILEGED)
        assert other.id != queued.id

    def test_can_await_approval(self, conn: sqlite3.Connection) -> None:
        (event_id,) = _event_ids(conn=conn, count=1)
        item = _enqueue(
            conn=conn,
            event_id=event_id,
            kind=WorkKind.PRIVILEGED,
            status=WorkStatus.AWAITING_APPROVAL,
        )
        assert item.status == WorkStatus.AWAITING_APPROVAL

    @pytest.mark.parametrize(
        "status",
        [WorkStatus.CLAIMED, WorkStatus.DONE, WorkStatus.REJECTED],
    )
    def test_rejects_non_initial_status(
        self,
        conn: sqlite3.Connection,
        queued: WorkItem,
        status: WorkStatus,
    ) -> None:
        result = enqueue(
            conn=conn,
            event_id=queued.event_id,
            kind=WorkKind.PRIVILEGED,
            now=NOW,
            status=status,
        )
        assert isinstance(result, ErrorResult)

    def test_rejects_unknown_event(self, conn: sqlite3.Connection) -> None:
        result = enqueue(conn=conn, event_id=999, kind=WorkKind.REPLY, now=NOW)
        assert isinstance(result, ErrorResult)
        assert result.details == {"event_id": 999}


class TestClaim:
    def test_sets_lease(self, claimed: WorkItem) -> None:
        assert (claimed.status, claimed.claimed_by, claimed.claimed_until, claimed.attempts) == (
            WorkStatus.CLAIMED,
            "session-a",
            to_db_time(moment=NOW + LEASE),
            1,
        )

    def test_empty_queue_returns_none(self, conn: sqlite3.Connection) -> None:
        assert _claim(conn=conn, claimer="session-a") is None

    def test_live_lease_is_not_claimable(
        self, conn: sqlite3.Connection, claimed: WorkItem
    ) -> None:
        assert _claim(conn=conn, claimer="session-b", minutes_later=4) is None

    def test_awaiting_approval_is_not_claimable(self, conn: sqlite3.Connection) -> None:
        (event_id,) = _event_ids(conn=conn, count=1)
        _enqueue(
            conn=conn,
            event_id=event_id,
            kind=WorkKind.PRIVILEGED,
            status=WorkStatus.AWAITING_APPROVAL,
        )
        assert _claim(conn=conn, claimer="session-a") is None

    def test_claims_oldest_first(self, conn: sqlite3.Connection) -> None:
        first, second = _event_ids(conn=conn, count=2)
        oldest = _enqueue(conn=conn, event_id=second)
        _enqueue(conn=conn, event_id=first)
        claimed = _claim(conn=conn, claimer="session-a")
        assert claimed is not None
        assert claimed.id == oldest.id

    @pytest.mark.parametrize("claimer", ["", "   "])
    def test_requires_claimer(self, conn: sqlite3.Connection, claimer: str) -> None:
        assert isinstance(claim(conn=conn, claimer=claimer, lease=LEASE, now=NOW), ErrorResult)

    @pytest.mark.parametrize("lease", [timedelta(0), timedelta(seconds=-1)])
    def test_requires_positive_lease(self, conn: sqlite3.Connection, lease: timedelta) -> None:
        assert isinstance(claim(conn=conn, claimer="session-a", lease=lease, now=NOW), ErrorResult)


class TestRestartMidClaim:
    """A session dies holding a claim; once the lease lapses, another session takes over."""

    @pytest.fixture
    def reclaimed(self, conn: sqlite3.Connection, claimed: WorkItem) -> WorkItem:
        item = _claim(conn=conn, claimer="session-b", minutes_later=6)
        assert item is not None
        return item

    def test_same_item_comes_back(self, claimed: WorkItem, reclaimed: WorkItem) -> None:
        assert reclaimed.id == claimed.id

    def test_new_owner_and_attempt(self, reclaimed: WorkItem) -> None:
        assert (reclaimed.claimed_by, reclaimed.attempts) == ("session-b", 2)

    def test_dead_claimer_cannot_ack(self, conn: sqlite3.Connection, reclaimed: WorkItem) -> None:
        result = ack(conn=conn, item_id=reclaimed.id, claimer="session-a", now=NOW)
        assert isinstance(result, ErrorResult)
        assert result.details == {"item_id": reclaimed.id, "claimer": "session-a"}


class TestAck:
    @pytest.fixture
    def acked(self, conn: sqlite3.Connection, claimed: WorkItem) -> WorkItem:
        result = ack(
            conn=conn, item_id=claimed.id, claimer="session-a", now=NOW, result="answered"
        )
        assert isinstance(result, SuccessResult)
        return result.value

    def test_marks_done_and_keeps_row(self, acked: WorkItem) -> None:
        assert (acked.status, acked.claimed_until, acked.result) == (
            WorkStatus.DONE,
            None,
            "answered",
        )

    def test_done_item_is_never_reclaimed(self, conn: sqlite3.Connection, acked: WorkItem) -> None:
        assert _claim(conn=conn, claimer="session-b", minutes_later=60) is None

    def test_second_ack_fails(self, conn: sqlite3.Connection, acked: WorkItem) -> None:
        assert isinstance(
            ack(conn=conn, item_id=acked.id, claimer="session-a", now=NOW),
            ErrorResult,
        )


class TestRelease:
    @pytest.fixture
    def released(self, conn: sqlite3.Connection, claimed: WorkItem) -> WorkItem:
        result = release(conn=conn, item_id=claimed.id, claimer="session-a", now=NOW)
        assert isinstance(result, SuccessResult)
        return result.value

    def test_returns_to_queue(self, released: WorkItem) -> None:
        assert (released.status, released.claimed_by, released.claimed_until) == (
            WorkStatus.QUEUED,
            None,
            None,
        )

    def test_is_claimable_at_once(self, conn: sqlite3.Connection, released: WorkItem) -> None:
        item = _claim(conn=conn, claimer="session-b")
        assert item is not None
        assert item.id == released.id

    def test_other_session_cannot_release(
        self, conn: sqlite3.Connection, claimed: WorkItem
    ) -> None:
        assert isinstance(
            release(conn=conn, item_id=claimed.id, claimer="session-b", now=NOW),
            ErrorResult,
        )


class TestLeaseBoundary:
    """The lease ends at claimed_until: from that instant the item is claimable again."""

    def test_claimable_exactly_at_expiry(
        self, conn: sqlite3.Connection, claimed: WorkItem
    ) -> None:
        item = _claim(conn=conn, claimer="session-b", minutes_later=5)
        assert item is not None
        assert item.id == claimed.id


class TestLateAckBeforeReclaim:
    """The lease lapsed but nobody took the item over; the original session may finish it."""

    @pytest.fixture
    def acked(self, conn: sqlite3.Connection, claimed: WorkItem) -> WorkItem:
        result = ack(
            conn=conn,
            item_id=claimed.id,
            claimer="session-a",
            now=NOW + timedelta(minutes=30),
        )
        assert isinstance(result, SuccessResult)
        return result.value

    def test_marks_done(self, acked: WorkItem) -> None:
        assert acked.status == WorkStatus.DONE


class TestStoreErrors:
    """A store whose work_items table is missing surfaces as an ErrorResult, not an exception."""

    @pytest.fixture
    def broken_store(self, conn: sqlite3.Connection, queued: WorkItem) -> sqlite3.Connection:
        conn.execute("ALTER TABLE work_items RENAME TO gone")
        return conn

    def test_enqueue(self, broken_store: sqlite3.Connection, queued: WorkItem) -> None:
        assert isinstance(
            enqueue(conn=broken_store, event_id=queued.event_id, kind=WorkKind.REPLY, now=NOW),
            ErrorResult,
        )

    def test_claim(self, broken_store: sqlite3.Connection) -> None:
        assert isinstance(
            claim(conn=broken_store, claimer="session-a", lease=LEASE, now=NOW),
            ErrorResult,
        )

    def test_ack(self, broken_store: sqlite3.Connection, queued: WorkItem) -> None:
        assert isinstance(
            ack(conn=broken_store, item_id=queued.id, claimer="session-a", now=NOW),
            ErrorResult,
        )

    def test_release(self, broken_store: sqlite3.Connection, queued: WorkItem) -> None:
        assert isinstance(
            release(conn=broken_store, item_id=queued.id, claimer="session-a", now=NOW),
            ErrorResult,
        )


@dataclass
class _Race:
    enqueued: list[int]
    claimed: list[int] = field(default_factory=list)
    errors: list[BaseException] = field(default_factory=list)
    stuck: list[str] = field(default_factory=list)


class TestConcurrentClaims:
    """Several sessions racing on one queue never receive the same item."""

    WORKERS = 4
    ITEMS = 24
    JOIN_TIMEOUT_SECONDS = 30

    @pytest.fixture
    def race(self, conn: sqlite3.Connection, db_path: Path) -> _Race:
        outcome = _Race(
            enqueued=[
                _enqueue(conn=conn, event_id=event_id).id
                for event_id in _event_ids(conn=conn, count=self.ITEMS)
            ]
        )
        guard = threading.Lock()
        start = threading.Barrier(self.WORKERS)

        def drain(name: str) -> None:
            try:
                opened = open_store(path=db_path)
                assert isinstance(opened, SuccessResult)
                worker = opened.value
                try:
                    start.wait(timeout=self.JOIN_TIMEOUT_SECONDS)
                    while (item := _claim(conn=worker, claimer=name)) is not None:
                        with guard:
                            outcome.claimed.append(item.id)
                finally:
                    worker.close()
            except BaseException as exc:
                with guard:
                    outcome.errors.append(exc)

        threads = [
            threading.Thread(target=drain, kwargs={"name": f"session-{index}"})
            for index in range(self.WORKERS)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=self.JOIN_TIMEOUT_SECONDS)
        outcome.stuck = [thread.name for thread in threads if thread.is_alive()]
        return outcome

    def test_no_worker_failed(self, race: _Race) -> None:
        assert race.errors == []

    def test_no_worker_hung(self, race: _Race) -> None:
        assert race.stuck == []

    def test_every_item_claimed_exactly_once(self, race: _Race) -> None:
        assert sorted(race.claimed) == sorted(race.enqueued)
