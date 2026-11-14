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
    defer,
    enqueue,
    get_item,
    hand_over,
    reject,
    release,
)
from dev10x.comm.chatbus.store import open_store
from tests.comm.chatbus.factories import NOW, SPACE, message_event, unwrap

LEASE = timedelta(minutes=5)


def _event_ids(*, conn: sqlite3.Connection, count: int) -> list[int]:
    events = [message_event(number=number) for number in range(1, count + 1)]
    unwrap(ingest_events(conn=conn, space=SPACE, events=events, now=NOW))
    return [row[0] for row in conn.execute("SELECT id FROM events ORDER BY id").fetchall()]


def _enqueue(
    *,
    conn: sqlite3.Connection,
    event_id: int,
    kind: WorkKind = WorkKind.REPLY,
    status: WorkStatus = WorkStatus.QUEUED,
) -> WorkItem:
    return unwrap(enqueue(conn=conn, event_id=event_id, kind=kind, now=NOW, status=status))


def _claim(*, conn: sqlite3.Connection, claimer: str, minutes_later: int = 0) -> WorkItem | None:
    return unwrap(
        claim(
            conn=conn,
            claimer=claimer,
            lease=LEASE,
            now=NOW + timedelta(minutes=minutes_later),
        )
    )


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

    @pytest.mark.parametrize(
        ("kind", "expected"),
        [(WorkKind.REPLY, "reply_item"), (WorkKind.PRIVILEGED, "privileged_item")],
    )
    def test_kind_limits_the_claim(
        self, conn: sqlite3.Connection, kind: WorkKind, expected: str
    ) -> None:
        first, second = _event_ids(conn=conn, count=2)
        items = {
            "privileged_item": _enqueue(conn=conn, event_id=first, kind=WorkKind.PRIVILEGED),
            "reply_item": _enqueue(conn=conn, event_id=second),
        }
        claimed = unwrap(claim(conn=conn, claimer="session-a", lease=LEASE, now=NOW, kind=kind))
        assert claimed is not None
        assert claimed.id == items[expected].id

    def test_kind_with_nothing_of_that_kind_returns_none(
        self, conn: sqlite3.Connection, queued: WorkItem
    ) -> None:
        result = claim(
            conn=conn, claimer="session-a", lease=LEASE, now=NOW, kind=WorkKind.PRIVILEGED
        )
        assert unwrap(result) is None

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


class TestHandOver:
    @pytest.fixture
    def handed(self, conn: sqlite3.Connection, claimed: WorkItem) -> WorkItem:
        return unwrap(
            hand_over(
                conn=conn,
                item_id=claimed.id,
                claimer="session-a",
                to="agent-b",
                lease=timedelta(hours=1),
                now=NOW,
                note="routed",
            )
        )

    def test_moves_the_claim(self, handed: WorkItem) -> None:
        assert (handed.status, handed.claimed_by, handed.claimed_until, handed.result) == (
            WorkStatus.CLAIMED,
            "agent-b",
            to_db_time(moment=NOW + timedelta(hours=1)),
            "routed",
        )

    def test_keeps_the_attempt_count(self, handed: WorkItem) -> None:
        assert handed.attempts == 1

    def test_new_holder_can_ack(self, conn: sqlite3.Connection, handed: WorkItem) -> None:
        assert unwrap(ack(conn=conn, item_id=handed.id, claimer="agent-b", now=NOW)).status == (
            WorkStatus.DONE
        )

    def test_old_holder_cannot_ack(self, conn: sqlite3.Connection, handed: WorkItem) -> None:
        assert isinstance(
            ack(conn=conn, item_id=handed.id, claimer="session-a", now=NOW), ErrorResult
        )

    @pytest.mark.parametrize(
        ("to", "lease"),
        [("", timedelta(hours=1)), ("  ", timedelta(hours=1)), ("agent-b", timedelta(0))],
    )
    def test_validates_arguments(
        self,
        conn: sqlite3.Connection,
        claimed: WorkItem,
        to: str,
        lease: timedelta,
    ) -> None:
        result = hand_over(
            conn=conn,
            item_id=claimed.id,
            claimer="session-a",
            to=to,
            lease=lease,
            now=NOW,
            note="x",
        )
        assert isinstance(result, ErrorResult)


class TestDefer:
    @pytest.mark.parametrize(("refund", "attempts"), [(True, 0), (False, 1)])
    def test_requeues_with_reason(
        self,
        conn: sqlite3.Connection,
        claimed: WorkItem,
        refund: bool,
        attempts: int,
    ) -> None:
        item = unwrap(
            defer(
                conn=conn,
                item_id=claimed.id,
                claimer="session-a",
                now=NOW,
                reason="herdr is down",
                refund_attempt=refund,
            )
        )
        assert (item.status, item.claimed_by, item.attempts, item.result) == (
            WorkStatus.QUEUED,
            None,
            attempts,
            "herdr is down",
        )

    def test_none_reason_keeps_the_recorded_one(
        self, conn: sqlite3.Connection, claimed: WorkItem
    ) -> None:
        unwrap(
            hand_over(
                conn=conn,
                item_id=claimed.id,
                claimer="session-a",
                to="session-a",
                lease=LEASE,
                now=NOW,
                note="first reason",
            )
        )
        item = unwrap(
            defer(
                conn=conn,
                item_id=claimed.id,
                claimer="session-a",
                now=NOW,
                reason=None,
                refund_attempt=True,
            )
        )
        assert item.result == "first reason"


class TestReject:
    def test_marks_rejected_with_reason(self, conn: sqlite3.Connection, claimed: WorkItem) -> None:
        item = unwrap(
            reject(conn=conn, item_id=claimed.id, claimer="session-a", now=NOW, reason="poison")
        )
        assert (item.status, item.claimed_until, item.result) == (
            WorkStatus.REJECTED,
            None,
            "poison",
        )

    def test_rejected_item_is_never_reclaimed(
        self, conn: sqlite3.Connection, claimed: WorkItem
    ) -> None:
        unwrap(
            reject(conn=conn, item_id=claimed.id, claimer="session-a", now=NOW, reason="poison")
        )
        assert _claim(conn=conn, claimer="session-b", minutes_later=60) is None

    def test_other_session_cannot_reject(
        self, conn: sqlite3.Connection, claimed: WorkItem
    ) -> None:
        result = reject(conn=conn, item_id=claimed.id, claimer="session-b", now=NOW, reason="x")
        assert isinstance(result, ErrorResult)


class TestGetItem:
    def test_reads_the_stored_row(self, conn: sqlite3.Connection, claimed: WorkItem) -> None:
        assert unwrap(get_item(conn=conn, item_id=claimed.id)) == claimed

    def test_unknown_item_is_an_error(self, conn: sqlite3.Connection) -> None:
        result = get_item(conn=conn, item_id=999)
        assert isinstance(result, ErrorResult)
        assert result.details == {"item_id": 999}


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

    def test_get_item(self, broken_store: sqlite3.Connection, queued: WorkItem) -> None:
        assert isinstance(get_item(conn=broken_store, item_id=queued.id), ErrorResult)


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
                worker = unwrap(open_store(path=db_path))
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

    def test_every_item_claimed_exactly_once(self, race: _Race) -> None:
        # One test, so the four-thread race runs once rather than per assertion.
        assert (race.errors, race.stuck, sorted(race.claimed)) == ([], [], sorted(race.enqueued))
