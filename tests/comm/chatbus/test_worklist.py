from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pytest
from dev10x.domain.common.result import Result, err, ok

from dev10x.comm.chatbus import worklist
from dev10x.comm.chatbus.events import (
    MESSAGE_CREATED,
    REACTION_CREATED,
    ChatEvent,
    EventSource,
)
from dev10x.comm.chatbus.ingest import ingest_events
from dev10x.comm.chatbus.queue import WorkItem, WorkKind, WorkStatus, claim, enqueue
from dev10x.comm.chatbus.worklist import (
    BotPoster,
    PostedReply,
    ReplyTarget,
    WorkView,
    get_view,
    list_work,
    reply,
    reply_target,
)
from dev10x.comm.skills.notifications import gchat_notify
from dev10x.comm.skills.notifications.gchat_notify import PostedMessage
from tests.comm.chatbus.factories import NOW, SPACE, expect_error, unwrap

LEASE = timedelta(minutes=5)
THREAD = f"{SPACE}/threads/t001"
MESSAGE = f"{SPACE}/messages/m001"
REACTION = f"{MESSAGE}/reactions/r001"


def _message(*, name: str = MESSAGE, thread: str | None = THREAD) -> ChatEvent:
    body: dict[str, Any] = {
        "name": name,
        "text": "@bot what is the status?",
        "argumentText": "what is the status?",
        "sender": {"name": "users/111"},
    }
    if thread is not None:
        body["thread"] = {"name": thread}
    return ChatEvent(
        type=MESSAGE_CREATED,
        resource_name=name,
        space=SPACE,
        sender="users/111",
        event_time=NOW,
        payload={"message": body},
        source=EventSource.POLL,
    )


def _reaction() -> ChatEvent:
    return ChatEvent(
        type=REACTION_CREATED,
        resource_name=REACTION,
        space=SPACE,
        sender="users/222",
        event_time=NOW + timedelta(seconds=1),
        payload={"reaction": {"name": REACTION, "emoji": {"unicode": "🤖"}}},
        source=EventSource.PUBSUB,
    )


def _store(*, conn: sqlite3.Connection, events: list[ChatEvent]) -> dict[str, int]:
    unwrap(ingest_events(conn=conn, space=SPACE, events=events, now=NOW))
    rows = conn.execute("SELECT id, resource_name FROM events").fetchall()
    return {row["resource_name"]: row["id"] for row in rows}


def _enqueue(
    *, conn: sqlite3.Connection, event_id: int, kind: WorkKind = WorkKind.REPLY
) -> WorkItem:
    return unwrap(enqueue(conn=conn, event_id=event_id, kind=kind, now=NOW))


def _claim(*, conn: sqlite3.Connection, claimer: str = "session-a") -> WorkItem:
    item = unwrap(claim(conn=conn, claimer=claimer, lease=LEASE, now=NOW))
    assert item is not None
    return item


@dataclass
class FakePoster:
    landed_thread: str | None = None
    failure: str | None = None
    calls: list[dict[str, str]] = field(default_factory=list)

    def post(self, *, space: str, thread: str, text: str) -> Result[PostedMessage]:
        self.calls.append({"space": space, "thread": thread, "text": text})
        if self.failure is not None:
            return err(self.failure)
        return ok(
            PostedMessage(name=f"{SPACE}/messages/reply1", thread=self.landed_thread or thread)
        )


@pytest.fixture
def event_ids(conn: sqlite3.Connection) -> dict[str, int]:
    return _store(conn=conn, events=[_message(), _reaction()])


@pytest.fixture
def reply_item(conn: sqlite3.Connection, event_ids: dict[str, int]) -> WorkItem:
    return _enqueue(conn=conn, event_id=event_ids[MESSAGE])


@pytest.fixture
def claimed(conn: sqlite3.Connection, reply_item: WorkItem) -> WorkItem:
    return _claim(conn=conn)


class TestListWork:
    @pytest.fixture
    def views(self, conn: sqlite3.Connection, reply_item: WorkItem) -> list[WorkView]:
        return unwrap(list_work(conn=conn))

    def test_shows_the_event_behind_the_item(self, views: list[WorkView]) -> None:
        assert [
            (view.event_type, view.space, view.sender, view.thread, view.untrusted_text)
            for view in views
        ] == [(MESSAGE_CREATED, SPACE, "users/111", THREAD, "what is the status?")]

    def test_to_dict_carries_item_and_event(self, views: list[WorkView]) -> None:
        assert views[0].to_dict() == {
            "id": views[0].item.id,
            "kind": "reply",
            "status": "queued",
            "claimed_by": None,
            "claimed_until": None,
            "attempts": 0,
            "result": None,
            "event_type": MESSAGE_CREATED,
            "space": SPACE,
            "sender": "users/111",
            "thread": THREAD,
            "untrusted_text": "what is the status?",
            "created_at": views[0].created_at,
        }

    def test_filters_by_status(self, conn: sqlite3.Connection, reply_item: WorkItem) -> None:
        assert unwrap(list_work(conn=conn, statuses=[WorkStatus.DONE])) == []

    def test_limit_caps_the_listing(
        self, conn: sqlite3.Connection, event_ids: dict[str, int]
    ) -> None:
        _enqueue(conn=conn, event_id=event_ids[MESSAGE])
        _enqueue(conn=conn, event_id=event_ids[REACTION], kind=WorkKind.PRIVILEGED)
        assert len(unwrap(list_work(conn=conn, limit=1))) == 1

    def test_reaction_takes_the_thread_of_its_message(
        self, conn: sqlite3.Connection, event_ids: dict[str, int]
    ) -> None:
        _enqueue(conn=conn, event_id=event_ids[REACTION], kind=WorkKind.PRIVILEGED)
        (view,) = unwrap(list_work(conn=conn))
        assert (view.thread, view.untrusted_text) == (THREAD, "🤖")

    def test_reaction_on_an_unknown_message_has_no_thread(self, conn: sqlite3.Connection) -> None:
        ids = _store(conn=conn, events=[_reaction()])
        _enqueue(conn=conn, event_id=ids[REACTION], kind=WorkKind.PRIVILEGED)
        (view,) = unwrap(list_work(conn=conn))
        assert view.thread is None

    def test_unreadable_payload_lists_with_no_text(
        self, conn: sqlite3.Connection, reply_item: WorkItem
    ) -> None:
        conn.execute("UPDATE events SET payload = 'not json'")
        (view,) = unwrap(list_work(conn=conn))
        assert (view.thread, view.untrusted_text) == (None, "")

    def test_requires_a_positive_limit(self, conn: sqlite3.Connection) -> None:
        assert expect_error(list_work(conn=conn, limit=0)).details == {"limit": 0}

    def test_requires_a_status(self, conn: sqlite3.Connection) -> None:
        expect_error(list_work(conn=conn, statuses=[]))

    def test_store_error_is_an_error_result(self, conn: sqlite3.Connection) -> None:
        conn.execute("ALTER TABLE work_items RENAME TO gone")
        expect_error(list_work(conn=conn))


class TestGetView:
    def test_unknown_item_is_an_error(self, conn: sqlite3.Connection) -> None:
        assert expect_error(get_view(conn=conn, item_id=999)).details == {"item_id": 999}

    def test_store_error_is_an_error_result(self, conn: sqlite3.Connection) -> None:
        conn.execute("ALTER TABLE work_items RENAME TO gone")
        expect_error(get_view(conn=conn, item_id=1))


class TestReplyTarget:
    def test_is_the_items_own_thread(self, conn: sqlite3.Connection, claimed: WorkItem) -> None:
        target = unwrap(reply_target(conn=conn, item_id=claimed.id, claimer="session-a", now=NOW))
        assert target == ReplyTarget(item_id=claimed.id, space=SPACE, thread=THREAD)

    @pytest.mark.parametrize(
        ("claimer", "minutes_later"),
        [("session-b", 0), ("session-a", 5)],
        ids=["other-session", "lapsed-lease"],
    )
    def test_needs_a_live_claim(
        self,
        conn: sqlite3.Connection,
        claimed: WorkItem,
        claimer: str,
        minutes_later: int,
    ) -> None:
        result = reply_target(
            conn=conn,
            item_id=claimed.id,
            claimer=claimer,
            now=NOW + timedelta(minutes=minutes_later),
        )
        assert expect_error(result).details["status"] == "claimed"

    def test_unclaimed_item_is_refused(
        self, conn: sqlite3.Connection, reply_item: WorkItem
    ) -> None:
        result = reply_target(conn=conn, item_id=reply_item.id, claimer="session-a", now=NOW)
        assert expect_error(result).details["status"] == "queued"

    def test_unknown_item_is_refused(self, conn: sqlite3.Connection) -> None:
        expect_error(reply_target(conn=conn, item_id=999, claimer="session-a", now=NOW))

    def test_item_without_a_thread_is_refused(self, conn: sqlite3.Connection) -> None:
        ids = _store(conn=conn, events=[_message(thread=None)])
        _enqueue(conn=conn, event_id=ids[MESSAGE])
        item = _claim(conn=conn)
        result = reply_target(conn=conn, item_id=item.id, claimer="session-a", now=NOW)
        assert expect_error(result).details == {"item_id": item.id}


class TestReply:
    def test_posts_into_the_items_thread(
        self, conn: sqlite3.Connection, claimed: WorkItem
    ) -> None:
        poster = FakePoster()
        posted = reply(
            conn=conn,
            item_id=claimed.id,
            claimer="session-a",
            text="All green.",
            now=NOW,
            poster=poster,
        )
        assert (unwrap(posted), poster.calls) == (
            PostedReply(item_id=claimed.id, message=f"{SPACE}/messages/reply1", thread=THREAD),
            [{"space": SPACE, "thread": THREAD, "text": "All green."}],
        )

    def test_empty_text_posts_nothing(self, conn: sqlite3.Connection, claimed: WorkItem) -> None:
        poster = FakePoster()
        result = reply(
            conn=conn, item_id=claimed.id, claimer="session-a", text="  ", now=NOW, poster=poster
        )
        expect_error(result)
        assert poster.calls == []

    def test_without_a_claim_posts_nothing(
        self, conn: sqlite3.Connection, reply_item: WorkItem
    ) -> None:
        poster = FakePoster()
        expect_error(
            reply(
                conn=conn,
                item_id=reply_item.id,
                claimer="session-a",
                text="hi",
                now=NOW,
                poster=poster,
            )
        )
        assert poster.calls == []

    def test_post_failure_is_reported(self, conn: sqlite3.Connection, claimed: WorkItem) -> None:
        result = reply(
            conn=conn,
            item_id=claimed.id,
            claimer="session-a",
            text="hi",
            now=NOW,
            poster=FakePoster(failure="HTTP 404"),
        )
        assert expect_error(result).error == "HTTP 404"

    def test_reply_outside_the_thread_is_an_error(
        self, conn: sqlite3.Connection, claimed: WorkItem
    ) -> None:
        result = reply(
            conn=conn,
            item_id=claimed.id,
            claimer="session-a",
            text="hi",
            now=NOW,
            poster=FakePoster(landed_thread=f"{SPACE}/threads/other"),
        )
        assert expect_error(result).details["observed_thread"] == f"{SPACE}/threads/other"


class TestBotPoster:
    @pytest.fixture
    def posted_with(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
        captured: dict[str, Any] = {}

        def fake_post(**kwargs: Any) -> Result[PostedMessage]:
            captured.update(kwargs)
            return ok(PostedMessage(name="n", thread=kwargs["thread"]))

        monkeypatch.setattr(gchat_notify, "mint_chat_token", lambda: ok("tok"))
        monkeypatch.setattr(gchat_notify, "post_message_detailed", fake_post)
        unwrap(BotPoster().post(space=SPACE, thread=THREAD, text="hi"))
        return captured

    def test_posts_as_the_bot_and_never_opens_a_new_thread(
        self, posted_with: dict[str, Any]
    ) -> None:
        assert posted_with == {
            "space_id": "AAAA",
            "token": "tok",
            "text": "hi",
            "thread": THREAD,
            "reply_option": gchat_notify.REPLY_OR_FAIL_OPTION,
        }

    def test_token_failure_posts_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(gchat_notify, "mint_chat_token", lambda: err("no credentials"))
        monkeypatch.setattr(
            gchat_notify,
            "post_message_detailed",
            lambda **_: pytest.fail("must not post without a token"),
        )
        result = BotPoster().post(space=SPACE, thread=THREAD, text="hi")
        assert expect_error(result).error == "no credentials"


def test_untrusted_notice_names_the_field() -> None:
    assert "untrusted_text" in worklist.UNTRUSTED_NOTICE
