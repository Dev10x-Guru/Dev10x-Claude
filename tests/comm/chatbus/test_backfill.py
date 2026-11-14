from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from dev10x.domain.common.result import Result, err, ok

from dev10x.comm.chatbus.authz import Allowlist, Outcome, authorize
from dev10x.comm.chatbus.backfill import (
    BackfillLimits,
    CatchUpReport,
    GapReason,
    Page,
    ReadBudget,
    SpaceBackfill,
    SubscriptionRecovery,
    backfill_space,
    catch_up,
    catch_up_due,
    open_gaps,
    record_gap,
    resolve_gaps,
)
from dev10x.comm.chatbus.events import (
    MESSAGE_CREATED,
    REACTION_CREATED,
    REACTION_DELETED,
    to_db_time,
)
from dev10x.comm.chatbus.ingest import Cursor, get_cursor, ingest_events
from dev10x.comm.chatbus.queue import WorkKind, claim, enqueue
from dev10x.comm.chatbus.snapshot import remember_reactions
from dev10x.comm.chatbus.sources.poll import WatchedSpace, message_event
from dev10x.comm.chatbus.sources.pubsub import (
    ACTIVE,
    ReceivedMessage,
    RenewalAction,
    SubscriptionSpec,
    SubscriptionState,
    event_from_pubsub,
    pull_once,
)
from dev10x.comm.chatbus.store import open_store
from tests.comm.chatbus.factories import NOW, SPACE, expect_error, unwrap

OTHER = "spaces/BBBB"
OWNER = "users/owner"
STRANGER = "users/stranger"
SPEC = SubscriptionSpec(topic="projects/p/topics/chat-bus")
SLEPT = timedelta(hours=6)


def message_name(number: int, space: str = SPACE) -> str:
    return f"{space}/messages/m{number:03d}"


def reaction_name(message: int, number: int, space: str = SPACE) -> str:
    return f"{message_name(message, space)}/reactions/r{number:03d}"


def raw_message(
    *,
    number: int,
    at: datetime,
    space: str = SPACE,
    summary: Mapping[str, int] | None = None,
    thread: str = "t1",
) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "name": message_name(number, space),
        "createTime": at.isoformat().replace("+00:00", "Z"),
        "sender": {"name": "users/111", "type": "HUMAN"},
        "thread": {"name": f"{space}/threads/{thread}"},
        "text": f"message {number}",
    }
    if summary:
        raw["emojiReactionSummaries"] = [
            {"emoji": {"unicode": emoji}, "reactionCount": count}
            for emoji, count in summary.items()
        ]
    return raw


def raw_reaction(
    *,
    message: int,
    number: int,
    emoji: str = "🤖",
    user: str = OWNER,
    space: str = SPACE,
) -> dict[str, Any]:
    return {
        "name": reaction_name(message, number, space),
        "user": {"name": user, "type": "HUMAN"},
        "emoji": {"unicode": emoji},
    }


@dataclass
class FakeHistory:
    messages: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    reactions: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    failing_spaces: frozenset[str] = frozenset()
    failing_messages: frozenset[str] = frozenset()
    calls: list[tuple[Any, ...]] = field(default_factory=list)

    @staticmethod
    def _page(*, items: list[dict[str, Any]], size: int, token: str | None) -> Page:
        start = int(token or 0)
        end = start + size
        return Page(
            items=list(items[start:end]),
            next_page_token=str(end) if end < len(items) else None,
        )

    def list_messages(
        self,
        *,
        space: str,
        since: datetime,
        threads: tuple[str, ...],
        page_size: int,
        page_token: str | None,
    ) -> Result[Page]:
        self.calls.append(("messages", space, since, threads, page_token))
        if space in self.failing_spaces:
            return err(f"Chat API refused {space}")
        listed = [
            raw
            for raw in self.messages.get(space, [])
            if _created(raw) > since
            and (not threads or raw["thread"]["name"] in threads)
        ]
        listed.sort(key=lambda raw: raw["createTime"])
        return ok(self._page(items=listed, size=page_size, token=page_token))

    def list_reactions(
        self,
        *,
        message: str,
        page_size: int,
        page_token: str | None,
    ) -> Result[Page]:
        self.calls.append(("reactions", message, page_token))
        if message in self.failing_messages:
            return err(f"Chat API refused {message}")
        return ok(
            self._page(items=self.reactions.get(message, []), size=page_size, token=page_token)
        )


def _created(raw: Mapping[str, Any]) -> datetime:
    return datetime.fromisoformat(str(raw["createTime"]).replace("Z", "+00:00"))


@dataclass
class FakeSubscriptions:
    live: SubscriptionState | None
    log: list[tuple[Any, ...]]
    fail: bool = False

    def get(self, *, name: str) -> Result[SubscriptionState | None]:
        return ok(self.live)

    def create(self, *, spec: SubscriptionSpec) -> Result[SubscriptionState]:
        self.log.append(("subscription", "create"))
        if self.fail:
            return err("Workspace Events refused")
        self.live = SubscriptionState(
            name="subscriptions/new", state=ACTIVE, expire_time=NOW + timedelta(hours=4)
        )
        return ok(self.live)

    def renew(self, *, name: str) -> Result[SubscriptionState]:
        raise AssertionError("a lapsed subscription is recreated, not renewed")

    def reactivate(self, *, name: str) -> Result[SubscriptionState]:
        raise AssertionError("a lapsed subscription is recreated, not reactivated")


@dataclass
class NoApprovals:
    def request_approval(
        self, *, owner: str, work_item_id: int, requester: str, verb: str
    ) -> Result[str]:
        raise AssertionError("no approval DM is expected")


def seed_poll(
    conn: sqlite3.Connection,
    *,
    raws: list[dict[str, Any]],
    space: str = SPACE,
    at: datetime,
) -> None:
    """What the live poll stored before the machine went to sleep."""
    events = [message_event(raw=raw, space=space, direct_message=False) for raw in raws]
    stored = [event for event in events if event is not None]
    newest = max(stored, key=lambda event: event.position)
    unwrap(
        ingest_events(
            conn=conn,
            space=space,
            events=stored,
            now=at,
            read_up_to=Cursor(event_time=newest.db_time, resource_name=newest.resource_name),
        )
    )


def seed_reaction(conn: sqlite3.Connection, *, raw: dict[str, Any], at: datetime) -> None:
    event = event_from_pubsub(message=pubsub_reaction(raw=raw, at=at))
    assert event is not None
    unwrap(ingest_events(conn=conn, space=event.space, events=[event], now=at))
    unwrap(remember_reactions(conn=conn, events=[event], now=at))


def pubsub_reaction(
    *,
    raw: dict[str, Any],
    at: datetime,
    event_type: str = REACTION_CREATED,
) -> ReceivedMessage:
    return ReceivedMessage(
        ack_id=f"ack-{raw['name']}",
        data=json.dumps({"reaction": raw}).encode(),
        attributes={
            "ce-type": event_type,
            "ce-time": at.isoformat().replace("+00:00", "Z"),
        },
    )


@dataclass(frozen=True)
class FakePuller:
    messages: list[ReceivedMessage]

    def pull(self, *, subscription: str, max_messages: int) -> Result[list[ReceivedMessage]]:
        return ok(list(self.messages))

    def ack(self, *, subscription: str, ack_ids: Any) -> Result[None]:
        return ok(None)


def event_keys(conn: sqlite3.Connection, *, event_type: str) -> list[str]:
    rows = conn.execute(
        "SELECT resource_name FROM events WHERE type = ? ORDER BY resource_name",
        (event_type,),
    ).fetchall()
    return [row[0] for row in rows]


def _catch_up(
    conn: sqlite3.Connection,
    history: FakeHistory,
    *,
    targets: tuple[WatchedSpace, ...] = (WatchedSpace(space=SPACE),),
    subscription: SubscriptionRecovery | None = None,
    limits: BackfillLimits = BackfillLimits(),
    now: datetime = NOW,
) -> CatchUpReport:
    return unwrap(
        catch_up(
            conn=conn,
            reader=history,
            targets=targets,
            now=now,
            subscription=subscription,
            limits=limits,
        )
    )


class TestCatchUpDue:
    @pytest.mark.parametrize(
        ("last_tick", "expected"),
        [
            (None, True),
            (NOW - timedelta(seconds=60), False),
            (NOW - timedelta(seconds=120), False),
            (NOW - timedelta(seconds=121), True),
            (NOW - SLEPT, True),
        ],
        ids=["start-up", "on-time", "twice-the-tick", "late", "slept"],
    )
    def test_runs_on_start_up_or_after_a_gap(
        self, last_tick: datetime | None, expected: bool
    ) -> None:
        assert catch_up_due(last_tick=last_tick, now=NOW, tick=timedelta(seconds=60)) is expected


class TestSleepBeyondTheSubscriptionTtl:
    """Acceptance: a lapsed subscription and a long sleep lose neither messages nor reactions."""

    @pytest.fixture
    def log(self) -> list[tuple[Any, ...]]:
        return []

    @pytest.fixture
    def history(self, conn: sqlite3.Connection, log: list[tuple[Any, ...]]) -> FakeHistory:
        before = NOW - SLEPT
        seed_poll(conn, raws=[raw_message(number=1, at=before)], at=before)
        seed_reaction(conn, raw=raw_reaction(message=1, number=1), at=before)
        history = FakeHistory(
            messages={
                SPACE: [
                    raw_message(number=1, at=before, summary={"👍": 1}),
                    raw_message(number=2, at=NOW - timedelta(hours=3), summary={"🤖": 1}),
                    raw_message(number=3, at=NOW - timedelta(hours=1)),
                ]
            },
            reactions={
                message_name(1): [raw_reaction(message=1, number=2, emoji="👍")],
                message_name(2): [raw_reaction(message=2, number=3)],
            },
        )
        history.calls = log
        return history

    @pytest.fixture
    def subscriptions(self, log: list[tuple[Any, ...]]) -> FakeSubscriptions:
        lapsed = SubscriptionState(
            name="subscriptions/old", state=ACTIVE, expire_time=NOW - timedelta(hours=2)
        )
        return FakeSubscriptions(live=lapsed, log=log)

    @pytest.fixture
    def report(
        self,
        conn: sqlite3.Connection,
        history: FakeHistory,
        subscriptions: FakeSubscriptions,
    ) -> CatchUpReport:
        conn.execute(
            "INSERT INTO subscriptions (target, name, expire_time, renewed_at) "
            "VALUES (?, 'subscriptions/old', ?, ?)",
            (
                SPEC.target_resource,
                to_db_time(moment=NOW - timedelta(hours=2)),
                to_db_time(moment=NOW - SLEPT),
            ),
        )
        return _catch_up(
            conn, history, subscription=SubscriptionRecovery(api=subscriptions, spec=SPEC)
        )

    def test_recreates_the_subscription_before_reading(
        self, report: CatchUpReport, log: list[tuple[Any, ...]]
    ) -> None:
        assert report.subscription is not None
        assert report.subscription.action is RenewalAction.RECREATED
        assert log[0] == ("subscription", "create")

    def test_recovers_the_missed_messages(
        self, conn: sqlite3.Connection, report: CatchUpReport
    ) -> None:
        assert event_keys(conn, event_type=MESSAGE_CREATED) == [
            message_name(1),
            message_name(2),
            message_name(3),
        ]
        assert report.spaces[SPACE].messages_inserted == 2

    def test_recovers_the_reactions_added_while_asleep(
        self, conn: sqlite3.Connection, report: CatchUpReport
    ) -> None:
        backfilled = conn.execute(
            "SELECT resource_name FROM events WHERE type = ? AND source = 'backfill' "
            "ORDER BY resource_name",
            (REACTION_CREATED,),
        ).fetchall()

        assert [row[0] for row in backfilled] == [reaction_name(1, 2), reaction_name(2, 3)]

    def test_infers_the_reaction_removed_while_asleep(
        self, conn: sqlite3.Connection, report: CatchUpReport
    ) -> None:
        assert event_keys(conn, event_type=REACTION_DELETED) == [reaction_name(1, 1)]
        assert report.spaces[SPACE].reactions_deleted == 1

    def test_backfilled_reaction_has_the_pubsub_shape(
        self, conn: sqlite3.Connection, report: CatchUpReport
    ) -> None:
        row = conn.execute(
            "SELECT sender, payload FROM events WHERE resource_name = ? AND type = ?",
            (reaction_name(2, 3), REACTION_CREATED),
        ).fetchone()

        assert (row[0], json.loads(row[1])) == (
            OWNER,
            {"reaction": raw_reaction(message=2, number=3)},
        )

    def test_rebuilds_a_deleted_reaction_from_the_snapshot(
        self, conn: sqlite3.Connection, report: CatchUpReport
    ) -> None:
        row = conn.execute(
            "SELECT payload FROM events WHERE type = ?", (REACTION_DELETED,)
        ).fetchone()

        assert json.loads(row[0]) == {
            "reaction": {
                "name": reaction_name(1, 1),
                "user": {"name": OWNER},
                "emoji": {"unicode": "🤖"},
            }
        }

    def test_the_snapshot_matches_what_chat_shows(
        self, conn: sqlite3.Connection, report: CatchUpReport
    ) -> None:
        rows = conn.execute(
            "SELECT reaction_name FROM reaction_snapshot ORDER BY reaction_name"
        ).fetchall()

        assert [row[0] for row in rows] == [reaction_name(1, 2), reaction_name(2, 3)]

    def test_advances_the_cursor_to_the_newest_message(
        self, conn: sqlite3.Connection, report: CatchUpReport
    ) -> None:
        cursor = get_cursor(conn=conn, space=SPACE)

        assert cursor is not None
        assert cursor.resource_name == message_name(3)

    def test_reads_from_the_cursor_minus_the_look_back(
        self, report: CatchUpReport, history: FakeHistory
    ) -> None:
        first_read = next(call for call in history.calls if call[0] == "messages")

        assert first_read[2] == NOW - SLEPT - timedelta(minutes=5)

    def test_records_no_gap(self, conn: sqlite3.Connection, report: CatchUpReport) -> None:
        assert (open_gaps(conn=conn), report.truncated, report.reads) == ([], False, 3)


class TestOverlapWithPubSub:
    """Acceptance: the same event from backfill and from Pub/Sub lands once."""

    @pytest.fixture
    def history(self, conn: sqlite3.Connection) -> FakeHistory:
        before = NOW - SLEPT
        seed_poll(conn, raws=[raw_message(number=1, at=before)], at=before)
        return FakeHistory(
            messages={SPACE: [raw_message(number=1, at=before, summary={"🤖": 1})]},
            reactions={message_name(1): [raw_reaction(message=1, number=1)]},
        )

    @pytest.fixture
    def late_delivery(self) -> FakePuller:
        return FakePuller(
            messages=[
                pubsub_reaction(
                    raw=raw_reaction(message=1, number=1), at=NOW - timedelta(minutes=1)
                )
            ]
        )

    def test_pubsub_first_then_backfill(
        self, conn: sqlite3.Connection, history: FakeHistory, late_delivery: FakePuller
    ) -> None:
        unwrap(pull_once(conn=conn, puller=late_delivery, subscription="s", now=NOW))

        report = _catch_up(conn, history)

        assert event_keys(conn, event_type=REACTION_CREATED) == [reaction_name(1, 1)]
        assert report.spaces[SPACE].reactions_created == 0

    def test_backfill_first_then_pubsub(
        self, conn: sqlite3.Connection, history: FakeHistory, late_delivery: FakePuller
    ) -> None:
        _catch_up(conn, history)

        pulled = unwrap(pull_once(conn=conn, puller=late_delivery, subscription="s", now=NOW))

        assert (pulled.inserted, pulled.duplicates) == (0, 1)
        assert event_keys(conn, event_type=REACTION_CREATED) == [reaction_name(1, 1)]

    def test_a_message_the_poll_stored_lands_once(
        self, conn: sqlite3.Connection, history: FakeHistory
    ) -> None:
        report = _catch_up(conn, history)

        assert event_keys(conn, event_type=MESSAGE_CREATED) == [message_name(1)]
        assert report.spaces[SPACE].duplicates == 1


class TestReactionAddedAndRemovedWhileAsleep:
    """Acceptance: a reaction that came and went during the downtime creates no event."""

    def test_creates_no_reaction_event(self, conn: sqlite3.Connection) -> None:
        before = NOW - SLEPT
        seed_poll(conn, raws=[raw_message(number=1, at=before)], at=before)
        history = FakeHistory(messages={SPACE: [raw_message(number=1, at=before)]})

        report = _catch_up(conn, history)

        assert event_keys(conn, event_type=REACTION_CREATED) == []
        assert event_keys(conn, event_type=REACTION_DELETED) == []
        assert report.spaces[SPACE].reactions_created == 0


class TestRestartMidClaim:
    """Acceptance: a claim held when the machine restarted comes back once its lease ends."""

    @pytest.fixture
    def item_id(self, db_path: Path) -> Iterator[int]:
        before = NOW - SLEPT
        conn = unwrap(open_store(path=db_path))
        seed_poll(conn, raws=[raw_message(number=1, at=before)], at=before)
        event_id = conn.execute("SELECT id FROM events").fetchone()[0]
        item = unwrap(enqueue(conn=conn, event_id=event_id, kind=WorkKind.REPLY, now=before))
        unwrap(claim(conn=conn, claimer="session-a", lease=timedelta(minutes=10), now=before))
        conn.close()
        yield item.id

    def test_is_held_while_the_lease_lasts(self, db_path: Path, item_id: int) -> None:
        conn = unwrap(open_store(path=db_path))

        claimed = unwrap(
            claim(
                conn=conn,
                claimer="session-b",
                lease=timedelta(minutes=10),
                now=NOW - SLEPT + timedelta(minutes=5),
            )
        )
        conn.close()

        assert claimed is None

    def test_is_reclaimable_after_the_lease_ends(self, db_path: Path, item_id: int) -> None:
        conn = unwrap(open_store(path=db_path))

        claimed = unwrap(
            claim(conn=conn, claimer="session-b", lease=timedelta(minutes=10), now=NOW)
        )
        conn.close()

        assert claimed is not None
        assert (claimed.id, claimed.claimed_by, claimed.attempts) == (item_id, "session-b", 2)


class TestWindowBeyondTheMaximum:
    """Acceptance: a window older than the maximum is recorded as a gap, not dropped."""

    @pytest.fixture
    def asleep_since(self) -> datetime:
        return NOW - timedelta(days=10)

    @pytest.fixture
    def history(self, conn: sqlite3.Connection, asleep_since: datetime) -> FakeHistory:
        seed_poll(conn, raws=[raw_message(number=1, at=asleep_since)], at=asleep_since)
        return FakeHistory(messages={SPACE: [raw_message(number=2, at=NOW - timedelta(days=1))]})

    @pytest.fixture
    def report(self, conn: sqlite3.Connection, history: FakeHistory) -> CatchUpReport:
        return _catch_up(conn, history)

    def test_records_the_lost_part_as_a_gap(
        self, conn: sqlite3.Connection, report: CatchUpReport, asleep_since: datetime
    ) -> None:
        gaps = open_gaps(conn=conn)

        assert [(gap.reason, gap.from_time, gap.to_time) for gap in gaps] == [
            (GapReason.WINDOW_EXCEEDED.value, asleep_since, NOW - timedelta(days=7))
        ]
        assert report.spaces[SPACE].window_exceeded

    def test_still_recovers_what_is_inside_the_window(
        self, conn: sqlite3.Connection, report: CatchUpReport, history: FakeHistory
    ) -> None:
        assert history.calls[0][2] == NOW - timedelta(days=7)
        assert message_name(2) in event_keys(conn, event_type=MESSAGE_CREATED)

    def test_a_second_run_widens_the_same_gap(
        self, conn: sqlite3.Connection, report: CatchUpReport
    ) -> None:
        gap_id = unwrap(
            record_gap(
                conn=conn,
                space=SPACE,
                start=NOW - timedelta(days=12),
                end=NOW - timedelta(days=6),
                reason=GapReason.WINDOW_EXCEEDED,
                now=NOW,
            )
        )

        gaps = open_gaps(conn=conn)
        assert [(gap.id, gap.from_time, gap.to_time) for gap in gaps] == [
            (gap_id, NOW - timedelta(days=12), NOW - timedelta(days=6))
        ]


class TestReadBudget:
    @pytest.fixture
    def limits(self) -> BackfillLimits:
        return BackfillLimits(max_reads=2, page_size=1)

    @pytest.fixture
    def history(self, conn: sqlite3.Connection) -> FakeHistory:
        before = NOW - SLEPT
        seed_poll(conn, raws=[raw_message(number=1, at=before)], at=before)
        return FakeHistory(
            messages={
                SPACE: [
                    raw_message(number=n, at=NOW - timedelta(hours=5 - n)) for n in range(2, 6)
                ]
            }
        )

    @pytest.fixture
    def first(
        self, conn: sqlite3.Connection, history: FakeHistory, limits: BackfillLimits
    ) -> CatchUpReport:
        return _catch_up(conn, history, limits=limits)

    def test_stops_at_the_budget(self, first: CatchUpReport) -> None:
        assert (first.reads, first.truncated) == (2, True)

    def test_keeps_the_cursor_where_it_stopped(
        self, conn: sqlite3.Connection, first: CatchUpReport
    ) -> None:
        cursor = get_cursor(conn=conn, space=SPACE)

        assert cursor is not None
        assert cursor.resource_name == message_name(3)

    def test_records_the_unread_rest_as_a_gap(
        self, conn: sqlite3.Connection, first: CatchUpReport
    ) -> None:
        assert [(gap.reason, gap.to_time) for gap in open_gaps(conn=conn)] == [
            (GapReason.READ_BUDGET.value, NOW)
        ]

    def test_the_next_run_continues_and_closes_the_gap(
        self, conn: sqlite3.Connection, first: CatchUpReport, history: FakeHistory
    ) -> None:
        later = NOW + timedelta(minutes=1)

        second = _catch_up(conn, history, now=later)

        assert second.truncated is False
        assert event_keys(conn, event_type=MESSAGE_CREATED) == [
            message_name(n) for n in range(1, 6)
        ]
        assert open_gaps(conn=conn) == []

    def test_one_budget_covers_every_space(
        self, conn: sqlite3.Connection, history: FakeHistory, limits: BackfillLimits
    ) -> None:
        seed_poll(conn, raws=[raw_message(number=1, at=NOW, space=OTHER)], space=OTHER, at=NOW)

        report = _catch_up(
            conn,
            history,
            targets=(WatchedSpace(space=SPACE), WatchedSpace(space=OTHER)),
            limits=limits,
        )

        assert (report.spaces[SPACE].reads, report.spaces[OTHER].reads) == (2, 0)
        assert report.spaces[OTHER].truncated


class TestPartialReactionListing:
    def test_a_listing_cut_by_the_budget_infers_no_deletion(
        self, conn: sqlite3.Connection
    ) -> None:
        before = NOW - SLEPT
        seed_poll(conn, raws=[raw_message(number=1, at=before)], at=before)
        seed_reaction(conn, raw=raw_reaction(message=1, number=1), at=before)
        seed_reaction(conn, raw=raw_reaction(message=1, number=2), at=before)
        history = FakeHistory(
            messages={SPACE: [raw_message(number=1, at=before, summary={"👍": 1})]},
            reactions={
                message_name(1): [
                    raw_reaction(message=1, number=1),
                    raw_reaction(message=1, number=2),
                ]
            },
        )

        report = _catch_up(conn, history, limits=BackfillLimits(max_reads=2, page_size=1))

        assert event_keys(conn, event_type=REACTION_DELETED) == []
        assert report.truncated


class TestTrackedMessages:
    def test_finds_a_deletion_on_a_message_older_than_the_window(
        self, conn: sqlite3.Connection
    ) -> None:
        old = NOW - timedelta(days=2)
        seed_poll(conn, raws=[raw_message(number=1, at=old)], at=old)
        seed_poll(conn, raws=[raw_message(number=2, at=NOW - SLEPT)], at=NOW - SLEPT)
        seed_reaction(conn, raw=raw_reaction(message=1, number=1), at=old)
        history = FakeHistory(messages={SPACE: [raw_message(number=2, at=NOW - SLEPT)]})

        _catch_up(conn, history)

        assert event_keys(conn, event_type=REACTION_DELETED) == [reaction_name(1, 1)]

    def test_reads_at_most_the_tracked_limit(self, conn: sqlite3.Connection) -> None:
        seed_poll(
            conn,
            raws=[raw_message(number=n, at=NOW - timedelta(hours=n)) for n in range(1, 4)],
            at=NOW,
        )
        history = FakeHistory()

        _catch_up(conn, history, limits=BackfillLimits(tracked_messages=2))

        assert [call[1] for call in history.calls if call[0] == "reactions"] == [
            message_name(1),
            message_name(2),
        ]


class TestBackfillSpace:
    def test_a_space_never_read_has_nothing_to_recover(self, conn: sqlite3.Connection) -> None:
        history = FakeHistory()

        report = unwrap(
            backfill_space(conn=conn, reader=history, target=WatchedSpace(space=SPACE), now=NOW)
        )

        assert (report, history.calls) == (SpaceBackfill(), [])

    def test_reads_only_the_watched_threads(self, conn: sqlite3.Connection) -> None:
        before = NOW - SLEPT
        seed_poll(conn, raws=[raw_message(number=1, at=before)], at=before)
        history = FakeHistory(
            messages={
                SPACE: [
                    raw_message(number=2, at=NOW - timedelta(hours=1), thread="t1"),
                    raw_message(number=3, at=NOW - timedelta(hours=1), thread="t2"),
                ]
            }
        )
        thread = f"{SPACE}/threads/t1"

        unwrap(
            backfill_space(
                conn=conn,
                reader=history,
                target=WatchedSpace(space=SPACE, threads=(thread,)),
                now=NOW,
                budget=ReadBudget(remaining=10),
            )
        )

        assert history.calls[0][3] == (thread,)
        assert event_keys(conn, event_type=MESSAGE_CREATED) == [message_name(1), message_name(2)]

    def test_flags_a_late_indexed_message_as_look_back_recovery(
        self, conn: sqlite3.Connection
    ) -> None:
        before = NOW - SLEPT
        seed_poll(conn, raws=[raw_message(number=2, at=before)], at=before)
        late = raw_message(number=1, at=before - timedelta(minutes=2))
        history = FakeHistory(messages={SPACE: [late, raw_message(number=2, at=before)]})

        report = unwrap(
            backfill_space(conn=conn, reader=history, target=WatchedSpace(space=SPACE), now=NOW)
        )

        assert report.recovered_by_lookback == 1

    def test_counts_what_it_cannot_parse(self, conn: sqlite3.Connection) -> None:
        before = NOW - SLEPT
        seed_poll(conn, raws=[raw_message(number=1, at=before)], at=before)
        nameless = raw_message(number=2, at=NOW)
        del nameless["name"]
        history = FakeHistory(
            messages={SPACE: [raw_message(number=1, at=before, summary={"🤖": 1}), nameless]},
            reactions={message_name(1): [{"name": reaction_name(9, 1)}]},
        )

        report = unwrap(
            backfill_space(conn=conn, reader=history, target=WatchedSpace(space=SPACE), now=NOW)
        )

        assert report.malformed == 2

    def test_reports_a_failed_ingest(self, conn: sqlite3.Connection) -> None:
        before = NOW - SLEPT
        seed_poll(conn, raws=[raw_message(number=1, at=before)], at=before)
        conn.execute(
            "CREATE TRIGGER refuse BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, 'full'); END"
        )
        history = FakeHistory(messages={SPACE: [raw_message(number=2, at=NOW)]})

        failed = expect_error(
            backfill_space(conn=conn, reader=history, target=WatchedSpace(space=SPACE), now=NOW)
        )

        assert "ingest failed" in failed.error

    def test_reports_a_failed_reaction_ingest(self, conn: sqlite3.Connection) -> None:
        before = NOW - SLEPT
        seed_poll(conn, raws=[raw_message(number=1, at=before)], at=before)
        conn.execute(
            "CREATE TRIGGER refuse BEFORE INSERT ON events "
            f"WHEN NEW.type = '{REACTION_CREATED}' BEGIN SELECT RAISE(ABORT, 'full'); END"
        )
        history = FakeHistory(reactions={message_name(1): [raw_reaction(message=1, number=1)]})

        failed = expect_error(
            backfill_space(conn=conn, reader=history, target=WatchedSpace(space=SPACE), now=NOW)
        )

        assert "ingest failed" in failed.error

    def test_reports_a_failed_snapshot_update(self, conn: sqlite3.Connection) -> None:
        before = NOW - SLEPT
        seed_poll(conn, raws=[raw_message(number=1, at=before)], at=before)
        conn.execute(
            "CREATE TRIGGER refuse BEFORE INSERT ON reaction_snapshot "
            "BEGIN SELECT RAISE(ABORT, 'full'); END"
        )
        history = FakeHistory(reactions={message_name(1): [raw_reaction(message=1, number=1)]})

        failed = expect_error(
            backfill_space(conn=conn, reader=history, target=WatchedSpace(space=SPACE), now=NOW)
        )

        assert "reaction snapshot" in failed.error

    @pytest.mark.parametrize(
        ("trigger", "now"),
        [
            ("BEFORE INSERT ON gaps", NOW + timedelta(days=10)),
            ("BEFORE UPDATE ON gaps", NOW),
        ],
        ids=["record", "resolve"],
    )
    def test_reports_a_failed_gap_write(
        self, conn: sqlite3.Connection, trigger: str, now: datetime
    ) -> None:
        seed_poll(conn, raws=[raw_message(number=1, at=NOW)], at=NOW)
        unwrap(
            record_gap(
                conn=conn,
                space=SPACE,
                start=NOW,
                end=NOW,
                reason=GapReason.READ_BUDGET,
                now=NOW,
            )
        )
        conn.execute(f"CREATE TRIGGER refuse {trigger} BEGIN SELECT RAISE(ABORT, 'full'); END")

        failed = expect_error(
            backfill_space(
                conn=conn, reader=FakeHistory(), target=WatchedSpace(space=SPACE), now=now
            )
        )

        assert "gap" in failed.error


class TestResolveGaps:
    def test_closes_only_the_named_kind(self, conn: sqlite3.Connection) -> None:
        for reason in GapReason:
            unwrap(record_gap(conn=conn, space=SPACE, start=NOW, end=NOW, reason=reason, now=NOW))

        resolved = unwrap(
            resolve_gaps(conn=conn, space=SPACE, reason=GapReason.READ_BUDGET, now=NOW)
        )

        assert resolved == 1
        assert [gap.reason for gap in open_gaps(conn=conn)] == [GapReason.WINDOW_EXCEEDED.value]


class TestCatchUpFailures:
    @pytest.fixture
    def seeded(self, conn: sqlite3.Connection) -> sqlite3.Connection:
        before = NOW - SLEPT
        seed_poll(conn, raws=[raw_message(number=1, at=before)], at=before)
        seed_poll(
            conn, raws=[raw_message(number=1, at=before, space=OTHER)], space=OTHER, at=before
        )
        return conn

    def test_one_failing_space_does_not_stop_the_others(self, seeded: sqlite3.Connection) -> None:
        history = FakeHistory(failing_spaces=frozenset({SPACE}))

        report = _catch_up(
            seeded, history, targets=(WatchedSpace(space=SPACE), WatchedSpace(space=OTHER))
        )

        assert (list(report.failures), list(report.spaces)) == ([SPACE], [OTHER])

    def test_reports_a_failed_reaction_listing(self, seeded: sqlite3.Connection) -> None:
        history = FakeHistory(failing_messages=frozenset({message_name(1)}))

        report = _catch_up(seeded, history)

        assert "refused" in report.failures[SPACE]

    def test_backfills_even_when_the_subscription_cannot_be_recovered(
        self, seeded: sqlite3.Connection
    ) -> None:
        log: list[tuple[Any, ...]] = []
        api = FakeSubscriptions(live=None, log=log, fail=True)
        history = FakeHistory(messages={SPACE: [raw_message(number=2, at=NOW)]})

        report = _catch_up(seeded, history, subscription=SubscriptionRecovery(api=api, spec=SPEC))

        assert (report.subscription, report.subscription_error) == (
            None,
            "Workspace Events refused",
        )
        assert report.spaces[SPACE].messages_inserted == 1

    def test_reads_at_most_the_space_cap(self, seeded: sqlite3.Connection) -> None:
        report = _catch_up(
            seeded,
            FakeHistory(),
            targets=(WatchedSpace(space=OTHER), WatchedSpace(space=SPACE)),
            limits=BackfillLimits(max_spaces=1),
        )

        assert (list(report.spaces), report.skipped) == ([SPACE], (OTHER,))

    def test_rejects_a_space_listed_twice(self, conn: sqlite3.Connection) -> None:
        failed = expect_error(
            catch_up(
                conn=conn,
                reader=FakeHistory(),
                targets=[WatchedSpace(space=SPACE), WatchedSpace(space=SPACE)],
                now=NOW,
            )
        )

        assert "once" in failed.error


class TestBackfilledEventsAreAuthorized:
    """A replayed event goes through the same allowlist as a live one (#1787 AC 8)."""

    @pytest.fixture
    def allowlist(self) -> Allowlist:
        return Allowlist(owner=OWNER, trusted=frozenset(), logins={})

    @pytest.mark.parametrize(
        ("user", "outcome"),
        [(OWNER, Outcome.QUEUED), (STRANGER, Outcome.REJECTED)],
        ids=["owner", "stranger"],
    )
    def test_a_backfilled_reaction_is_checked(
        self,
        conn: sqlite3.Connection,
        allowlist: Allowlist,
        user: str,
        outcome: Outcome,
    ) -> None:
        before = NOW - SLEPT
        seed_poll(conn, raws=[raw_message(number=1, at=before)], at=before)
        history = FakeHistory(
            reactions={message_name(1): [raw_reaction(message=1, number=1, user=user)]}
        )
        _catch_up(conn, history)
        event_id = conn.execute(
            "SELECT id FROM events WHERE type = ? AND source = 'backfill'", (REACTION_CREATED,)
        ).fetchone()[0]

        verdict = unwrap(
            authorize(
                conn=conn,
                event_id=event_id,
                allowlist=allowlist,
                bot_user="users/bot",
                notifier=NoApprovals(),
                now=NOW,
            )
        )

        assert verdict.outcome is outcome
