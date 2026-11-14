from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from dev10x.comm.chatbus.backfill import GapReason, record_gap
from dev10x.comm.chatbus.events import to_db_time
from dev10x.comm.chatbus.ingest import ingest_events
from dev10x.comm.chatbus.queue import WorkKind, claim, enqueue
from dev10x.comm.chatbus.status import (
    BusStatus,
    empty_queue,
    get_status,
    read_status,
    render_status,
)
from tests.comm.chatbus.factories import NOW, SPACE, expect_error, message_event, unwrap

EMPTY_QUEUE = {
    "queued": 0,
    "awaiting_approval": 0,
    "claimed": 0,
    "done": 0,
    "rejected": 0,
}


class TestMissingStore:
    @pytest.fixture
    def status(self, tmp_path: Path) -> BusStatus:
        return unwrap(get_status(path=tmp_path / "chat-bus" / "bus.sqlite3", now=NOW))

    def test_reads_as_empty(self, status: BusStatus) -> None:
        assert (status.exists, status.queue, status.gaps) == (False, EMPTY_QUEUE, ())

    def test_is_not_created_by_looking(self, status: BusStatus) -> None:
        assert not status.store.parent.exists()

    def test_renders_a_hint(self, status: BusStatus) -> None:
        assert "not created yet" in render_status(status=status, now=NOW, service="inactive")


class TestEmptyStore:
    @pytest.fixture
    def status(self, conn: sqlite3.Connection, db_path: Path) -> BusStatus:
        return unwrap(get_status(path=db_path, now=NOW))

    def test_reports_zeros(self, status: BusStatus) -> None:
        assert (status.exists, status.subscriptions, status.cursors) == (True, (), ())
        assert (status.queue, status.expired_leases, status.gaps) == (EMPTY_QUEUE, 0, ())

    def test_renders_every_section(self, status: BusStatus) -> None:
        rendered = render_status(status=status, now=NOW, service="inactive")
        assert rendered.splitlines() == [
            "Service: inactive",
            f"Store: {status.store}",
            "Subscription:",
            "  none recorded",
            "Cursors:",
            "  none yet",
            "Queue: queued 0, awaiting_approval 0, claimed 0, done 0, rejected 0; "
            "expired leases 0",
            "Open gaps: 0",
        ]

    def test_serializes_to_json_shape(self, status: BusStatus) -> None:
        assert status.to_dict(now=NOW) == {
            "store": str(status.store),
            "exists": True,
            "subscriptions": [],
            "cursors": [],
            "queue": EMPTY_QUEUE,
            "expired_leases": 0,
            "gaps": [],
        }


class TestPopulatedStore:
    @pytest.fixture
    def status(self, conn: sqlite3.Connection, db_path: Path) -> BusStatus:
        earlier = NOW - timedelta(hours=3)
        conn.execute(
            "INSERT INTO subscriptions VALUES (?, ?, ?, ?)",
            (
                "//chat.googleapis.com/spaces/-",
                "subscriptions/live",
                to_db_time(moment=NOW + timedelta(minutes=30)),
                to_db_time(moment=NOW - timedelta(minutes=30)),
            ),
        )
        conn.execute(
            "INSERT INTO subscriptions VALUES (?, ?, ?, ?)",
            (
                "spaces/OLD",
                "subscriptions/lapsed",
                to_db_time(moment=NOW - timedelta(days=3)),
                to_db_time(moment=NOW - timedelta(days=4)),
            ),
        )
        event = message_event(number=1, minutes_ago=90)
        report = unwrap(
            ingest_events(
                conn=conn, space=SPACE, events=[event, message_event(number=2)], now=earlier
            )
        )
        assert report.inserted == 2
        conn.execute(
            "INSERT INTO cursors VALUES (?, ?, ?, ?)",
            (SPACE, event.db_time, event.resource_name, to_db_time(moment=earlier)),
        )
        unwrap(enqueue(conn=conn, event_id=1, kind=WorkKind.REPLY, now=earlier))
        unwrap(enqueue(conn=conn, event_id=2, kind=WorkKind.REPLY, now=earlier))
        unwrap(claim(conn=conn, claimer="s1", lease=timedelta(minutes=5), now=earlier))
        unwrap(
            record_gap(
                conn=conn,
                space=SPACE,
                start=NOW - timedelta(days=9),
                end=NOW - timedelta(days=7),
                reason=GapReason.WINDOW_EXCEEDED,
                now=earlier,
            )
        )
        return unwrap(get_status(path=db_path, now=NOW))

    def test_counts_the_queue(self, status: BusStatus) -> None:
        assert status.queue == {**EMPTY_QUEUE, "queued": 1, "claimed": 1}
        assert status.expired_leases == 1

    def test_renders_expiry_ages_and_gaps(self, status: BusStatus) -> None:
        rendered = render_status(status=status, now=NOW, service="active")
        assert "  subscriptions/live (expires in 30m, renewed 30m ago)" in rendered
        assert "  subscriptions/lapsed (EXPIRED, renewed 4d ago)" in rendered
        assert f"  {SPACE}: last event 90m ago, advanced 3h ago" in rendered
        assert "Open gaps: 1" in rendered
        assert "(window_exceeded)" in rendered

    def test_serializes_ages_in_seconds(self, status: BusStatus) -> None:
        payload = status.to_dict(now=NOW)
        assert payload["subscriptions"][0]["expires_in_seconds"] == 1800
        assert payload["cursors"][0]["event_age_seconds"] == 5400
        assert payload["gaps"][0]["reason"] == "window_exceeded"


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (timedelta(seconds=45), "45s ago"),
        (timedelta(minutes=5), "5m ago"),
        (timedelta(hours=5), "5h ago"),
        (timedelta(days=3), "3d ago"),
    ],
)
def test_ages_use_the_coarsest_readable_unit(
    conn: sqlite3.Connection, db_path: Path, age: timedelta, expected: str
) -> None:
    conn.execute(
        "INSERT INTO cursors VALUES (?, ?, ?, ?)",
        (SPACE, to_db_time(moment=NOW - age), "m", to_db_time(moment=NOW - age)),
    )
    status = unwrap(get_status(path=db_path, now=NOW))
    assert f"last event {expected}" in render_status(status=status, now=NOW, service="active")


def test_a_cursor_from_the_future_reads_as_ahead(conn: sqlite3.Connection, db_path: Path) -> None:
    ahead = to_db_time(moment=NOW + timedelta(seconds=30))
    conn.execute("INSERT INTO cursors VALUES (?, ?, ?, ?)", (SPACE, ahead, "m", ahead))
    status = unwrap(get_status(path=db_path, now=NOW))
    assert "last event 30s ahead" in render_status(status=status, now=NOW, service="active")


def test_an_unreadable_store_is_an_error(conn: sqlite3.Connection, db_path: Path) -> None:
    conn.execute("DROP TABLE gaps")
    assert (
        "Cannot read the Chat bus status"
        in expect_error(read_status(conn=conn, path=db_path, now=NOW)).error
    )


def test_a_store_that_cannot_open_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "bus.sqlite3"
    path.mkdir()
    assert "Cannot" in expect_error(get_status(path=path, now=NOW)).error


def test_empty_queue_lists_every_status() -> None:
    assert empty_queue() == EMPTY_QUEUE
