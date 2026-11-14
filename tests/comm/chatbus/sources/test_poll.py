from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pytest
from dev10x.domain.common.result import Result, err, ok

from dev10x.comm.chatbus.events import EventSource
from dev10x.comm.chatbus.ingest import Cursor, count_recovered_by_lookback, get_cursor
from dev10x.comm.chatbus.sources.poll import (
    PollLimits,
    PollTick,
    SpacePoll,
    WatchedSpace,
    message_event,
    poll_space,
    poll_tick,
    watched_from_watches,
)
from dev10x.comm.skills.notifications.gchat_watch import Watch
from tests.comm.chatbus.factories import NOW, SPACE, expect_error, unwrap

OTHER = "spaces/BBBB"
THREAD = f"{SPACE}/threads/t1"
SECOND_THREAD = f"{SPACE}/threads/t2"


def raw_message(
    *,
    number: int,
    minutes_ago: float,
    space: str = SPACE,
    sender: Any = None,
) -> dict[str, Any]:
    moment = NOW - timedelta(minutes=minutes_ago)
    return {
        "resource": f"{space}/messages/m{number:03d}",
        "createTime": moment.isoformat().replace("+00:00", "Z"),
        "sender": sender
        if sender is not None
        else {"name": "users/111", "displayName": "Ann", "type": "HUMAN"},
        "thread": f"{space}/threads/t1",
        "text": f"message {number}",
    }


@dataclass
class FakeReader:
    pages: dict[tuple[str, str | None], list[dict[str, Any]]] = field(default_factory=dict)
    failing: frozenset[tuple[str, str | None]] = frozenset()
    calls: list[tuple[str, str | None, int]] = field(default_factory=list)

    def __call__(
        self,
        *,
        space: str,
        thread: str | None,
        max_results: int,
    ) -> Result[list[Mapping[str, Any]]]:
        self.calls.append((space, thread, max_results))
        if (space, thread) in self.failing:
            return err(f"gog failed for {space}")
        return ok(list(self.pages.get((space, thread), [])))


def _poll(
    *,
    conn: sqlite3.Connection,
    reader: FakeReader,
    target: WatchedSpace = WatchedSpace(space=SPACE),
    limits: PollLimits = PollLimits(),
) -> SpacePoll:
    return unwrap(poll_space(conn=conn, reader=reader, target=target, now=NOW, limits=limits))


def _payload(conn: sqlite3.Connection, *, number: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT payload FROM events WHERE resource_name = ?",
        (f"{SPACE}/messages/m{number:03d}",),
    ).fetchone()
    return json.loads(row[0])


def _fail_event_inserts(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TRIGGER refuse BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, 'full'); END"
    )


class TestFirstPoll:
    @pytest.fixture
    def reader(self) -> FakeReader:
        page = [raw_message(number=2, minutes_ago=1), raw_message(number=1, minutes_ago=2)]
        return FakeReader(pages={(SPACE, None): page})

    @pytest.fixture
    def polled(self, conn: sqlite3.Connection, reader: FakeReader) -> SpacePoll:
        return _poll(conn=conn, reader=reader)

    def test_stores_every_message(self, polled: SpacePoll) -> None:
        assert (polled.read, polled.report.inserted, polled.malformed) == (2, 2, 0)

    def test_reads_one_page_of_the_whole_space(
        self, polled: SpacePoll, reader: FakeReader
    ) -> None:
        assert reader.calls == [(SPACE, None, 100)]

    def test_cursor_points_at_the_newest_message(
        self, conn: sqlite3.Connection, polled: SpacePoll
    ) -> None:
        cursor = get_cursor(conn=conn, space=SPACE)
        assert cursor is not None
        assert cursor.resource_name == f"{SPACE}/messages/m002"

    def test_payload_has_the_pubsub_message_shape(
        self, conn: sqlite3.Connection, polled: SpacePoll
    ) -> None:
        assert _payload(conn, number=1)["message"] == {
            "name": f"{SPACE}/messages/m001",
            "createTime": raw_message(number=1, minutes_ago=2)["createTime"],
            "sender": {"name": "users/111", "displayName": "Ann", "type": "HUMAN"},
            "thread": {"name": THREAD},
            "space": {"name": SPACE},
            "text": "message 1",
        }

    def test_is_stored_as_a_poll_event(self, conn: sqlite3.Connection, polled: SpacePoll) -> None:
        sources = {row[0] for row in conn.execute("SELECT source FROM events")}
        assert sources == {EventSource.POLL.value}

    def test_is_not_truncated(self, polled: SpacePoll) -> None:
        assert polled.truncated is False


class TestRepeatedPoll:
    """A message seen by the poll and again by its look-back window is stored once."""

    @pytest.fixture
    def second(self, conn: sqlite3.Connection) -> SpacePoll:
        page = [raw_message(number=2, minutes_ago=1), raw_message(number=1, minutes_ago=2)]
        reader = FakeReader(pages={(SPACE, None): page})
        _poll(conn=conn, reader=reader)
        return _poll(conn=conn, reader=reader)

    def test_inserts_nothing_new(self, second: SpacePoll) -> None:
        assert (second.report.inserted, second.report.duplicates) == (0, 2)

    def test_keeps_one_row_per_message(self, conn: sqlite3.Connection, second: SpacePoll) -> None:
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2


class TestLateIndexedMessage:
    @pytest.fixture
    def second(self, conn: sqlite3.Connection) -> SpacePoll:
        reader = FakeReader(pages={(SPACE, None): [raw_message(number=2, minutes_ago=1)]})
        _poll(conn=conn, reader=reader)
        reader.pages[(SPACE, None)] = [
            raw_message(number=2, minutes_ago=1),
            raw_message(number=1, minutes_ago=4),
            raw_message(number=0, minutes_ago=7),
        ]
        return _poll(conn=conn, reader=reader)

    def test_recovers_the_message_inside_the_window(self, second: SpacePoll) -> None:
        assert (second.report.inserted, second.report.recovered_by_lookback) == (1, 1)

    def test_flags_it_via_lookback(self, conn: sqlite3.Connection, second: SpacePoll) -> None:
        flagged = conn.execute(
            "SELECT resource_name FROM events WHERE via_lookback = 1"
        ).fetchall()
        assert [row[0] for row in flagged] == [f"{SPACE}/messages/m001"]

    def test_ignores_messages_behind_the_window(
        self, conn: sqlite3.Connection, second: SpacePoll
    ) -> None:
        names = {row[0] for row in conn.execute("SELECT resource_name FROM events")}
        assert f"{SPACE}/messages/m000" not in names

    def test_recovered_counts_are_queryable(
        self, conn: sqlite3.Connection, second: SpacePoll
    ) -> None:
        assert count_recovered_by_lookback(conn=conn) == {SPACE: 1}

    def test_count_since_a_later_time_is_empty(
        self, conn: sqlite3.Connection, second: SpacePoll
    ) -> None:
        later = NOW + timedelta(seconds=1)
        assert count_recovered_by_lookback(conn=conn, since=later) == {}


class TestDirectMessage:
    @pytest.fixture
    def payload(self, conn: sqlite3.Connection) -> dict[str, Any]:
        page = [raw_message(number=1, minutes_ago=1, sender="users/222")]
        _poll(
            conn=conn,
            reader=FakeReader(pages={(SPACE, None): page}),
            target=WatchedSpace(space=SPACE, direct_message=True),
        )
        return _payload(conn, number=1)["message"]

    def test_marks_the_space_as_a_dm(self, payload: dict[str, Any]) -> None:
        assert payload["space"] == {"name": SPACE, "spaceType": "DIRECT_MESSAGE"}

    def test_string_sender_becomes_a_user_resource(self, payload: dict[str, Any]) -> None:
        assert payload["sender"] == {"name": "users/222"}


class TestMalformedMessages:
    @pytest.fixture
    def polled(self, conn: sqlite3.Connection) -> SpacePoll:
        page = [
            raw_message(number=1, minutes_ago=1),
            {"resource": f"{SPACE}/messages/x", "createTime": ""},
            raw_message(number=2, minutes_ago=1, space=OTHER),
        ]
        return _poll(conn=conn, reader=FakeReader(pages={(SPACE, None): page}))

    def test_counts_what_it_could_not_store(self, polled: SpacePoll) -> None:
        assert (polled.read, polled.report.inserted, polled.malformed) == (3, 1, 2)


class TestThreadTargets:
    def test_reads_each_thread(self, conn: sqlite3.Connection) -> None:
        reader = FakeReader(
            pages={
                (SPACE, THREAD): [raw_message(number=1, minutes_ago=2)],
                (SPACE, SECOND_THREAD): [raw_message(number=2, minutes_ago=1)],
            }
        )

        polled = _poll(
            conn=conn,
            reader=reader,
            target=WatchedSpace(space=SPACE, threads=(THREAD, SECOND_THREAD)),
        )

        assert (polled.report.inserted, [call[1] for call in reader.calls]) == (
            2,
            [THREAD, SECOND_THREAD],
        )

    def test_one_unreadable_thread_stores_nothing(self, conn: sqlite3.Connection) -> None:
        reader = FakeReader(
            pages={(SPACE, THREAD): [raw_message(number=1, minutes_ago=2)]},
            failing=frozenset({(SPACE, SECOND_THREAD)}),
        )

        result = poll_space(
            conn=conn,
            reader=reader,
            target=WatchedSpace(space=SPACE, threads=(THREAD, SECOND_THREAD)),
            now=NOW,
        )

        assert "gog failed" in expect_error(result).error
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


class TestTruncation:
    LIMITS = PollLimits(page_size=2)

    def test_a_full_page_inside_the_window_is_truncated(self, conn: sqlite3.Connection) -> None:
        reader = FakeReader(pages={(SPACE, None): [raw_message(number=1, minutes_ago=1)]})
        _poll(conn=conn, reader=reader, limits=self.LIMITS)
        reader.pages[(SPACE, None)] = [
            raw_message(number=3, minutes_ago=0),
            raw_message(number=2, minutes_ago=0.5),
        ]

        assert _poll(conn=conn, reader=reader, limits=self.LIMITS).truncated is True

    def test_a_full_page_reaching_behind_the_window_is_complete(
        self, conn: sqlite3.Connection
    ) -> None:
        reader = FakeReader(pages={(SPACE, None): [raw_message(number=1, minutes_ago=1)]})
        _poll(conn=conn, reader=reader, limits=self.LIMITS)
        reader.pages[(SPACE, None)] = [
            raw_message(number=3, minutes_ago=0),
            raw_message(number=2, minutes_ago=9),
        ]

        assert _poll(conn=conn, reader=reader, limits=self.LIMITS).truncated is False

    def test_a_full_unparseable_page_is_truncated(self, conn: sqlite3.Connection) -> None:
        reader = FakeReader(pages={(SPACE, None): [raw_message(number=1, minutes_ago=1)]})
        _poll(conn=conn, reader=reader, limits=self.LIMITS)
        reader.pages[(SPACE, None)] = [{"createTime": ""}, {"createTime": ""}]

        assert _poll(conn=conn, reader=reader, limits=self.LIMITS).truncated is True

    def test_a_full_first_page_is_not_a_gap(self, conn: sqlite3.Connection) -> None:
        page = [raw_message(number=2, minutes_ago=0), raw_message(number=1, minutes_ago=1)]

        polled = _poll(
            conn=conn, reader=FakeReader(pages={(SPACE, None): page}), limits=self.LIMITS
        )

        assert polled.truncated is False


class TestIngestFailure:
    def test_returns_the_store_error(self, conn: sqlite3.Connection) -> None:
        _fail_event_inserts(conn)
        reader = FakeReader(pages={(SPACE, None): [raw_message(number=1, minutes_ago=1)]})

        result = poll_space(conn=conn, reader=reader, target=WatchedSpace(space=SPACE), now=NOW)

        assert "full" in expect_error(result).error


class TestPollTick:
    def test_one_failing_space_does_not_stop_the_others(self, conn: sqlite3.Connection) -> None:
        reader = FakeReader(
            pages={(SPACE, None): [raw_message(number=1, minutes_ago=1)]},
            failing=frozenset({(OTHER, None)}),
        )

        tick = unwrap(
            poll_tick(
                conn=conn,
                reader=reader,
                targets=[WatchedSpace(space=OTHER), WatchedSpace(space=SPACE)],
                now=NOW,
            )
        )

        assert (list(tick.spaces), list(tick.failures)) == ([SPACE], [OTHER])

    def test_caps_the_watched_spaces(self, conn: sqlite3.Connection) -> None:
        reader = FakeReader()

        tick = unwrap(
            poll_tick(
                conn=conn,
                reader=reader,
                targets=[WatchedSpace(space=OTHER), WatchedSpace(space=SPACE)],
                now=NOW,
                limits=PollLimits(max_spaces=1),
            )
        )

        assert (tick.skipped, [call[0] for call in reader.calls]) == ((OTHER,), [SPACE])

    def test_refuses_a_space_listed_twice(self, conn: sqlite3.Connection) -> None:
        result = poll_tick(
            conn=conn,
            reader=FakeReader(),
            targets=[WatchedSpace(space=SPACE), WatchedSpace(space=SPACE, threads=(THREAD,))],
            now=NOW,
        )

        assert expect_error(result).details == {"spaces": [SPACE]}

    def test_sums_lookback_recoveries(self, conn: sqlite3.Connection) -> None:
        reader = FakeReader(pages={(SPACE, None): [raw_message(number=2, minutes_ago=1)]})
        targets = [WatchedSpace(space=SPACE)]
        poll_tick(conn=conn, reader=reader, targets=targets, now=NOW)
        reader.pages[(SPACE, None)].append(raw_message(number=1, minutes_ago=3))

        tick = unwrap(poll_tick(conn=conn, reader=reader, targets=targets, now=NOW))

        assert tick.recovered_by_lookback == 1

    def test_an_empty_tick_recovers_nothing(self) -> None:
        assert PollTick().recovered_by_lookback == 0


class TestWatchedFromWatches:
    @staticmethod
    def watch(*, space: str, thread: str | None, expires_in: timedelta) -> Watch:
        return Watch(
            id=f"{space}.{thread}",
            space=space,
            thread=thread,
            notify=("inbox",),
            notify_roles=(),
            route=False,
            mode="ttl",
            armed_at=NOW - timedelta(hours=1),
            expires_at=NOW + expires_in,
        )

    def test_folds_watches_into_poll_targets(self) -> None:
        live = timedelta(hours=1)
        watches = [
            self.watch(space=SPACE, thread=SECOND_THREAD, expires_in=live),
            self.watch(space=SPACE, thread=THREAD, expires_in=live),
            self.watch(space=SPACE, thread=THREAD, expires_in=live),
            self.watch(space=OTHER, thread=None, expires_in=live),
            self.watch(space=OTHER, thread=f"{OTHER}/threads/x", expires_in=live),
            self.watch(space="spaces/CCCC", thread=None, expires_in=-live),
        ]

        assert watched_from_watches(watches=watches, now=NOW) == [
            WatchedSpace(space=SPACE, threads=(THREAD, SECOND_THREAD)),
            WatchedSpace(space=OTHER),
        ]


class TestMessageEvent:
    def test_a_naive_time_is_not_stored(self) -> None:
        raw = raw_message(number=1, minutes_ago=1)
        raw["createTime"] = "2026-11-06T11:59:00"

        event = message_event(raw=raw, space=SPACE, direct_message=False)

        assert event is not None
        assert event.event_time.tzinfo is not None

    def test_cursor_matches_the_ingested_position(self) -> None:
        event = message_event(
            raw=raw_message(number=1, minutes_ago=1), space=SPACE, direct_message=False
        )

        assert event is not None
        assert Cursor(event_time=event.db_time, resource_name=event.resource_name).position == (
            event.position
        )
