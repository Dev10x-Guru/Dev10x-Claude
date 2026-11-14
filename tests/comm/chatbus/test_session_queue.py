from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from dev10x.domain.common.result import Result, err, ok

from dev10x.comm.chatbus import queue, session_queue, worklist
from dev10x.comm.chatbus.events import MESSAGE_CREATED, ChatEvent, EventSource
from dev10x.comm.chatbus.ingest import ingest_events
from dev10x.comm.chatbus.queue import WorkKind, enqueue
from dev10x.comm.skills.notifications.gchat_notify import PostedMessage
from tests.comm.chatbus.factories import NOW, SPACE, expect_error, unwrap

LEASE = timedelta(minutes=15)
THREAD = f"{SPACE}/threads/t001"


class ThreadPoster:
    def post(self, *, space: str, thread: str, text: str) -> Result[PostedMessage]:
        return ok(PostedMessage(name=f"{SPACE}/messages/reply1", thread=thread))


def _event(*, number: int) -> ChatEvent:
    name = f"{SPACE}/messages/m{number:03d}"
    return ChatEvent(
        type=MESSAGE_CREATED,
        resource_name=name,
        space=SPACE,
        sender="users/111",
        event_time=NOW,
        payload={"message": {"name": name, "text": "hi", "thread": {"name": THREAD}}},
        source=EventSource.POLL,
    )


@pytest.fixture
def item_ids(conn: sqlite3.Connection) -> list[int]:
    unwrap(ingest_events(conn=conn, space=SPACE, events=[_event(number=1)], now=NOW))
    (event_id,) = [row[0] for row in conn.execute("SELECT id FROM events").fetchall()]
    reply = unwrap(enqueue(conn=conn, event_id=event_id, kind=WorkKind.REPLY, now=NOW))
    privileged = unwrap(enqueue(conn=conn, event_id=event_id, kind=WorkKind.PRIVILEGED, now=NOW))
    return [reply.id, privileged.id]


def _claim(*, path: Path, kind: str = "reply") -> dict[str, Any]:
    return unwrap(
        session_queue.claim_item(claimer="session-a", kind=kind, lease=LEASE, now=NOW, path=path)
    )


class TestRoundTrip:
    """claim → reply → ack against a temporary store (GH-1842 acceptance)."""

    @pytest.fixture
    def trip(self, db_path: Path, item_ids: list[int]) -> dict[str, dict[str, Any]]:
        claimed = _claim(path=db_path)
        item_id = claimed["item"]["id"]
        replied = unwrap(
            session_queue.reply_to_item(
                item_id=item_id,
                claimer="session-a",
                text="All green.",
                now=NOW,
                poster=ThreadPoster(),
                path=db_path,
            )
        )
        acked = unwrap(
            session_queue.ack_item(
                item_id=item_id, claimer="session-a", result="answered", now=NOW, path=db_path
            )
        )
        listed = unwrap(session_queue.list_items(status=["done"], limit=10, path=db_path))
        return {"claimed": claimed, "replied": replied, "acked": acked, "listed": listed}

    def test_claim_is_verified(self, trip: dict[str, dict[str, Any]], item_ids: list[int]) -> None:
        claimed = trip["claimed"]
        assert (
            claimed["claimed"],
            claimed["item"]["id"],
            claimed["observed_status"],
            claimed["claim_verified"],
        ) == (True, item_ids[0], "claimed", True)

    def test_reply_lands_in_the_thread(self, trip: dict[str, dict[str, Any]]) -> None:
        assert trip["replied"]["thread"] == THREAD

    def test_ack_is_verified(self, trip: dict[str, dict[str, Any]]) -> None:
        acked = trip["acked"]
        assert (acked["observed_status"], acked["result"], acked["ack_verified"]) == (
            "done",
            "answered",
            True,
        )

    def test_done_item_is_listed(self, trip: dict[str, dict[str, Any]]) -> None:
        listed = trip["listed"]
        assert (listed["count"], listed["items"][0]["result"]) == (1, "answered")


class TestListItems:
    def test_defaults_to_open_items(self, db_path: Path, item_ids: list[int]) -> None:
        listed = unwrap(session_queue.list_items(status=None, limit=10, path=db_path))
        assert ([item["id"] for item in listed["items"]], listed["notice"]) == (
            item_ids,
            worklist.UNTRUSTED_NOTICE,
        )

    def test_rejects_an_unknown_status(self, db_path: Path) -> None:
        result = session_queue.list_items(status=["open", "done"], limit=10, path=db_path)
        assert expect_error(result).details == {"unknown": ["open"]}

    def test_reports_a_bad_limit(self, db_path: Path) -> None:
        expect_error(session_queue.list_items(status=None, limit=0, path=db_path))

    def test_reports_an_unopenable_store(self, tmp_path: Path) -> None:
        blocker = tmp_path / "file"
        blocker.write_text("")
        expect_error(session_queue.list_items(status=None, limit=10, path=blocker / "bus.db"))

    def test_uses_the_default_store(self, db_path: Path, item_ids: list[int]) -> None:
        listed = unwrap(session_queue.list_items(status=None, limit=10))
        assert listed["count"] == 2


class TestClaimItem:
    def test_privileged_kind_claims_privileged_work(
        self, db_path: Path, item_ids: list[int]
    ) -> None:
        assert _claim(path=db_path, kind="privileged")["item"]["id"] == item_ids[1]

    def test_empty_queue_claims_nothing(self, db_path: Path) -> None:
        assert _claim(path=db_path) == {"claimed": False}

    def test_rejects_an_unknown_kind(self, db_path: Path) -> None:
        result = session_queue.claim_item(
            claimer="session-a", kind="any", lease=LEASE, now=NOW, path=db_path
        )
        assert expect_error(result).details == {"kind": "any"}

    def test_reports_a_claim_error(self, db_path: Path) -> None:
        result = session_queue.claim_item(
            claimer=" ", kind="reply", lease=LEASE, now=NOW, path=db_path
        )
        expect_error(result)

    def test_reports_a_failed_read_back(
        self, db_path: Path, item_ids: list[int], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(worklist, "get_view", lambda **_: err("read failed"))
        result = session_queue.claim_item(
            claimer="session-a", kind="reply", lease=LEASE, now=NOW, path=db_path
        )
        assert expect_error(result).error == "read failed"


class TestReplyToItem:
    def test_refuses_without_a_claim(self, db_path: Path, item_ids: list[int]) -> None:
        result = session_queue.reply_to_item(
            item_id=item_ids[0],
            claimer="session-a",
            text="hi",
            now=NOW,
            poster=ThreadPoster(),
            path=db_path,
        )
        assert expect_error(result).details["status"] == "queued"


class TestAckItem:
    def test_refuses_without_a_claim(self, db_path: Path, item_ids: list[int]) -> None:
        result = session_queue.ack_item(
            item_id=item_ids[0], claimer="session-a", result="", now=NOW, path=db_path
        )
        expect_error(result)

    def test_reports_a_failed_read_back(
        self, db_path: Path, item_ids: list[int], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _claim(path=db_path)
        monkeypatch.setattr(queue, "get_item", lambda **_: err("read failed"))
        result = session_queue.ack_item(
            item_id=item_ids[0], claimer="session-a", result="", now=NOW, path=db_path
        )
        assert expect_error(result).error == "read failed"
