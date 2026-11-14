"""Thread context handed to a session that claims Chat work (GH-1950)."""

from __future__ import annotations

import sqlite3
from datetime import timedelta

import pytest

from dev10x.comm.chatbus.events import (
    MESSAGE_CREATED,
    REACTION_CREATED,
    ChatEvent,
    EventSource,
)
from dev10x.comm.chatbus.ingest import ingest_events
from dev10x.comm.chatbus.queue import WorkKind, enqueue
from dev10x.comm.chatbus.worklist import (
    CONTEXT_LABEL,
    THREAD_CONTEXT_NOTICE,
    ContextPost,
    WorkView,
    get_view,
    thread_context,
)
from tests.comm.chatbus.factories import NOW, SPACE, expect_error, unwrap

THREAD = f"{SPACE}/threads/t001"
OTHER_THREAD = f"{SPACE}/threads/t002"
OWNER = "users/111"
ASKER = "users/222"
BOT = "users/999"
MAX_AGE = timedelta(hours=24)


def _name(*, number: int) -> str:
    return f"{SPACE}/messages/m{number:03d}"


def _post(
    *,
    number: int,
    minutes_ago: int,
    text: str,
    sender: str = OWNER,
    thread: str = THREAD,
    sender_type: str = "HUMAN",
) -> ChatEvent:
    name = _name(number=number)
    return ChatEvent(
        type=MESSAGE_CREATED,
        resource_name=name,
        space=SPACE,
        sender=sender,
        event_time=NOW - timedelta(minutes=minutes_ago),
        payload={
            "message": {
                "name": name,
                "text": text,
                "sender": {"name": sender, "type": sender_type},
                "thread": {"name": thread},
            }
        },
        source=EventSource.POLL,
    )


def _reaction(*, on: int, minutes_ago: int) -> ChatEvent:
    name = f"{_name(number=on)}/reactions/r001"
    return ChatEvent(
        type=REACTION_CREATED,
        resource_name=name,
        space=SPACE,
        sender=OWNER,
        event_time=NOW - timedelta(minutes=minutes_ago),
        payload={"reaction": {"name": name, "emoji": {"unicode": "🤖"}}},
        source=EventSource.PUBSUB,
    )


THREAD_EVENTS = [
    _post(number=0, minutes_ago=30, text="it is the staging deploy, not prod"),
    _post(number=1, minutes_ago=20, text="@bot why did it fail?", sender=ASKER),
    _post(number=2, minutes_ago=15, text="looking", sender=BOT, sender_type="BOT"),
    _post(number=3, minutes_ago=10, text="the retry passed, ignore that"),
    _post(number=4, minutes_ago=12, text="unrelated", thread=OTHER_THREAD),
    _post(number=5, minutes_ago=3 * 24 * 60, text="last week's news"),
    _reaction(on=1, minutes_ago=5),
]


@pytest.fixture
def event_ids(conn: sqlite3.Connection) -> dict[str, int]:
    unwrap(ingest_events(conn=conn, space=SPACE, events=THREAD_EVENTS, now=NOW))
    rows = conn.execute("SELECT id, resource_name FROM events").fetchall()
    return {row["resource_name"]: row["id"] for row in rows}


def _view_of(
    *, conn: sqlite3.Connection, event_id: int, kind: WorkKind = WorkKind.REPLY
) -> WorkView:
    item = unwrap(enqueue(conn=conn, event_id=event_id, kind=kind, now=NOW))
    return unwrap(get_view(conn=conn, item_id=item.id))


@pytest.fixture
def trigger(conn: sqlite3.Connection, event_ids: dict[str, int]) -> WorkView:
    return _view_of(conn=conn, event_id=event_ids[_name(number=1)])


def _context(*, conn: sqlite3.Connection, view: WorkView, limit: int = 20) -> list[ContextPost]:
    return unwrap(thread_context(conn=conn, view=view, now=NOW, limit=limit, max_age=MAX_AGE))


class TestSelection:
    @pytest.fixture
    def posts(self, conn: sqlite3.Connection, trigger: WorkView) -> list[ContextPost]:
        return _context(conn=conn, view=trigger)

    def test_keeps_the_threads_human_posts_around_the_trigger(
        self, posts: list[ContextPost]
    ) -> None:
        assert [(post.message, post.follows_trigger) for post in posts] == [
            (_name(number=0), False),
            (_name(number=3), True),
        ]

    def test_keeps_the_owners_unaddressed_text(self, posts: list[ContextPost]) -> None:
        assert [(post.sender, post.untrusted_text) for post in posts] == [
            (OWNER, "it is the staging deploy, not prod"),
            (OWNER, "the retry passed, ignore that"),
        ]

    def test_wraps_each_post_as_untrusted(self, posts: list[ContextPost]) -> None:
        assert posts[0].to_dict() == {
            "label": CONTEXT_LABEL,
            "message": _name(number=0),
            "sender": OWNER,
            "posted_at": "2026-11-06T11:30:00.000000Z",
            "follows_trigger": False,
            "untrusted_text": "it is the staging deploy, not prod",
        }


class TestBounds:
    def test_count_keeps_the_most_recent(
        self, conn: sqlite3.Connection, trigger: WorkView
    ) -> None:
        posts = _context(conn=conn, view=trigger, limit=1)
        assert [post.message for post in posts] == [_name(number=3)]

    def test_zero_limit_returns_nothing(self, conn: sqlite3.Connection, trigger: WorkView) -> None:
        assert _context(conn=conn, view=trigger, limit=0) == []

    def test_age_drops_old_posts(self, conn: sqlite3.Connection, trigger: WorkView) -> None:
        posts = unwrap(
            thread_context(
                conn=conn, view=trigger, now=NOW, limit=20, max_age=timedelta(minutes=15)
            )
        )
        assert [post.message for post in posts] == [_name(number=3)]


class TestTriggers:
    def test_reaction_trigger_sees_the_message_it_reacted_to(
        self, conn: sqlite3.Connection, event_ids: dict[str, int]
    ) -> None:
        reaction = f"{_name(number=1)}/reactions/r001"
        view = _view_of(conn=conn, event_id=event_ids[reaction], kind=WorkKind.PRIVILEGED)
        posts = _context(conn=conn, view=view)
        assert [(post.message, post.follows_trigger) for post in posts] == [
            (_name(number=0), False),
            (_name(number=1), False),
            (_name(number=3), False),
        ]

    def test_item_without_a_thread_has_no_context(
        self, conn: sqlite3.Connection, event_ids: dict[str, int]
    ) -> None:
        conn.execute(
            "UPDATE events SET payload = '{}' WHERE resource_name = ?", (_name(number=1),)
        )
        view = _view_of(conn=conn, event_id=event_ids[_name(number=1)])
        assert _context(conn=conn, view=view) == []


class TestFailures:
    def test_unreadable_payload_is_skipped(
        self, conn: sqlite3.Connection, trigger: WorkView
    ) -> None:
        conn.execute(
            "UPDATE events SET payload = 'not json' WHERE resource_name = ?", (_name(number=0),)
        )
        assert [post.message for post in _context(conn=conn, view=trigger)] == [_name(number=3)]

    def test_store_error_is_an_error_result(
        self, conn: sqlite3.Connection, trigger: WorkView
    ) -> None:
        conn.execute("ALTER TABLE events RENAME TO gone")
        result = thread_context(conn=conn, view=trigger, now=NOW, limit=20, max_age=MAX_AGE)
        assert expect_error(result).details == {"item_id": trigger.item.id}


def test_notice_names_the_context_field() -> None:
    assert ("thread_context" in THREAD_CONTEXT_NOTICE, "untrusted" in THREAD_CONTEXT_NOTICE) == (
        True,
        True,
    )
