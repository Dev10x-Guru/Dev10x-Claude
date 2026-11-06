from __future__ import annotations

import json
import sqlite3

import pytest
from dev10x.domain.common.result import ErrorResult

from dev10x.comm.chatbus.events import (
    REACTION_CREATED,
    REACTION_DELETED,
    ChatEvent,
    EventSource,
)
from dev10x.comm.chatbus.ingest import Cursor, IngestReport, get_cursor, ingest_events
from tests.comm.chatbus.factories import NOW, SPACE, expect_error, message_event, unwrap


def _ingest(
    *,
    conn: sqlite3.Connection,
    events: list[ChatEvent],
    read_up_to: Cursor | None = None,
) -> IngestReport:
    return unwrap(
        ingest_events(conn=conn, space=SPACE, events=events, now=NOW, read_up_to=read_up_to)
    )


def _cursor_after(event: ChatEvent) -> Cursor:
    return Cursor.at(event_time=event.event_time, resource_name=event.resource_name)


class TestFirstIngest:
    @pytest.fixture
    def report(self, conn: sqlite3.Connection) -> IngestReport:
        events = [message_event(number=1, minutes_ago=2), message_event(number=2, minutes_ago=1)]
        return _ingest(conn=conn, events=events, read_up_to=_cursor_after(events[-1]))

    def test_inserts_every_event(self, report: IngestReport) -> None:
        assert (report.inserted, report.duplicates) == (2, 0)

    def test_nothing_counts_as_lookback(self, report: IngestReport) -> None:
        assert report.recovered_by_lookback == 0

    def test_stores_cursor(self, conn: sqlite3.Connection, report: IngestReport) -> None:
        assert get_cursor(conn=conn, space=SPACE) == report.cursor

    def test_cursor_points_at_last_read(self, report: IngestReport) -> None:
        assert report.cursor == _cursor_after(message_event(number=2, minutes_ago=1))

    def test_keeps_payload(self, conn: sqlite3.Connection, report: IngestReport) -> None:
        raw = conn.execute("SELECT payload FROM events ORDER BY id LIMIT 1").fetchone()[0]
        assert json.loads(raw) == {
            "message": {"name": f"{SPACE}/messages/m001", "text": "message 1"},
        }


class TestDuplicateAcrossSources:
    """A late Pub/Sub delivery of an event backfill already stored lands once."""

    @pytest.fixture
    def report(self, conn: sqlite3.Connection) -> IngestReport:
        _ingest(conn=conn, events=[message_event(number=1, source=EventSource.BACKFILL)])
        return _ingest(conn=conn, events=[message_event(number=1, source=EventSource.PUBSUB)])

    def test_counts_duplicate(self, report: IngestReport) -> None:
        assert (report.inserted, report.duplicates) == (0, 1)

    def test_keeps_first_source(self, conn: sqlite3.Connection, report: IngestReport) -> None:
        rows = conn.execute("SELECT source FROM events").fetchall()
        assert [row[0] for row in rows] == ["backfill"]


class TestReactionLifecycleKeys:
    @pytest.fixture
    def report(self, conn: sqlite3.Connection) -> IngestReport:
        name = f"{SPACE}/messages/m001/reactions/r1"
        events = [
            ChatEvent(
                type=event_type,
                resource_name=name,
                space=SPACE,
                sender="users/111",
                event_time=NOW,
                payload={"reaction": {"name": name}},
                source=EventSource.PUBSUB,
            )
            for event_type in (REACTION_CREATED, REACTION_DELETED)
        ]
        return _ingest(conn=conn, events=events)

    def test_created_and_deleted_are_distinct(self, report: IngestReport) -> None:
        assert report.inserted == 2


class TestLookBackRecovery:
    """A message indexed late sits behind the cursor; the look-back re-read finds it."""

    @pytest.fixture
    def report(self, conn: sqlite3.Connection) -> IngestReport:
        newest = message_event(number=5, minutes_ago=1)
        _ingest(conn=conn, events=[newest], read_up_to=_cursor_after(newest))
        late = message_event(number=4, minutes_ago=3)
        return _ingest(conn=conn, events=[late, newest], read_up_to=_cursor_after(newest))

    def test_counts_recovered_event(self, report: IngestReport) -> None:
        assert (report.inserted, report.duplicates, report.recovered_by_lookback) == (1, 1, 1)

    def test_flags_recovered_row(self, conn: sqlite3.Connection, report: IngestReport) -> None:
        row = conn.execute(
            "SELECT via_lookback FROM events WHERE resource_name = ?",
            (f"{SPACE}/messages/m004",),
        ).fetchone()
        assert row[0] == 1


class TestLatePushDelivery:
    """A Pub/Sub event behind the cursor arrived late; the look-back did not find it."""

    @pytest.fixture
    def report(self, conn: sqlite3.Connection) -> IngestReport:
        newest = message_event(number=5, minutes_ago=1)
        _ingest(conn=conn, events=[newest], read_up_to=_cursor_after(newest))
        late = message_event(number=4, minutes_ago=3, source=EventSource.PUBSUB)
        return _ingest(conn=conn, events=[late])

    def test_not_counted_as_lookback(self, report: IngestReport) -> None:
        assert (report.inserted, report.recovered_by_lookback) == (1, 0)

    def test_row_not_flagged(self, conn: sqlite3.Connection, report: IngestReport) -> None:
        row = conn.execute(
            "SELECT via_lookback FROM events WHERE resource_name = ?",
            (f"{SPACE}/messages/m004",),
        ).fetchone()
        assert row[0] == 0


class TestCursorNeverRegresses:
    @pytest.fixture
    def report(self, conn: sqlite3.Connection) -> IngestReport:
        newest = message_event(number=9, minutes_ago=1)
        _ingest(conn=conn, events=[newest], read_up_to=_cursor_after(newest))
        older = message_event(number=3, minutes_ago=10)
        return _ingest(conn=conn, events=[older], read_up_to=_cursor_after(older))

    def test_keeps_newer_cursor(self, conn: sqlite3.Connection, report: IngestReport) -> None:
        assert get_cursor(conn=conn, space=SPACE) == _cursor_after(
            message_event(number=9, minutes_ago=1)
        )


class TestPushSourceLeavesCursor:
    @pytest.fixture
    def report(self, conn: sqlite3.Connection) -> IngestReport:
        return _ingest(conn=conn, events=[message_event(number=1, source=EventSource.PUBSUB)])

    def test_no_cursor_stored(self, conn: sqlite3.Connection, report: IngestReport) -> None:
        assert (report.cursor, get_cursor(conn=conn, space=SPACE)) == (None, None)


class TestCursorWaitsForCommit:
    """A failed batch must not move the cursor past events it never stored."""

    @pytest.fixture
    def result(self, conn: sqlite3.Connection) -> ErrorResult:
        conn.execute(
            "CREATE TRIGGER reject_m002 BEFORE INSERT ON events"
            f" WHEN NEW.resource_name = '{SPACE}/messages/m002'"
            " BEGIN SELECT RAISE(ABORT, 'disk full'); END"
        )
        events = [message_event(number=1, minutes_ago=2), message_event(number=2, minutes_ago=1)]
        return expect_error(
            ingest_events(
                conn=conn,
                space=SPACE,
                events=events,
                now=NOW,
                read_up_to=_cursor_after(events[-1]),
            )
        )

    def test_reports_error(self, result: ErrorResult) -> None:
        assert "disk full" in result.error

    def test_cursor_unchanged(self, conn: sqlite3.Connection, result: ErrorResult) -> None:
        assert get_cursor(conn=conn, space=SPACE) is None

    def test_no_partial_rows(self, conn: sqlite3.Connection, result: ErrorResult) -> None:
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


class TestForeignSpace:
    @pytest.fixture
    def result(self, conn: sqlite3.Connection) -> ErrorResult:
        stray = message_event(number=1, space="spaces/BBBB")
        return expect_error(ingest_events(conn=conn, space=SPACE, events=[stray], now=NOW))

    def test_names_foreign_space(self, result: ErrorResult) -> None:
        assert result.details == {"spaces": ["spaces/BBBB"]}
