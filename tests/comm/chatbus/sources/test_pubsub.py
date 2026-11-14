from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pytest
from dev10x.domain.common.result import ErrorResult, Result, err, ok

from dev10x.comm.chatbus.events import REACTION_CREATED, REACTION_DELETED, EventSource
from dev10x.comm.chatbus.sources.pubsub import (
    ALL_SPACES,
    PullReport,
    ReceivedMessage,
    RenewalAction,
    SubscriptionSpec,
    SubscriptionState,
    SubscriptionStatus,
    ensure_subscription,
    event_from_pubsub,
    get_subscription,
    pull_once,
    renewal_due,
)
from tests.comm.chatbus.factories import NOW, SPACE, expect_error, unwrap

OTHER = "spaces/BBBB"
SUBSCRIPTION = "projects/p/subscriptions/chat-bus"
SPEC = SubscriptionSpec(topic="projects/p/topics/chat-bus")
OLD = "subscriptions/old"
NEW = "subscriptions/new"


def reaction(
    *,
    number: int,
    event_type: str = REACTION_CREATED,
    space: str = SPACE,
    attributes: dict[str, str] | None = None,
    data: bytes | None = None,
    publish_time: datetime | None = None,
) -> ReceivedMessage:
    name = f"{space}/messages/m001/reactions/r{number:03d}"
    body = {"reaction": {"name": name, "user": {"name": "users/111"}, "emoji": {"unicode": "🤖"}}}
    return ReceivedMessage(
        ack_id=f"ack-{space[-1]}{number}",
        data=json.dumps(body).encode() if data is None else data,
        attributes={"ce-type": event_type, "ce-time": "2026-11-06T11:59:00Z"}
        if attributes is None
        else attributes,
        publish_time=publish_time,
    )


@dataclass
class FakePuller:
    messages: list[ReceivedMessage] = field(default_factory=list)
    pull_error: str | None = None
    ack_error: str | None = None
    acked: list[list[str]] = field(default_factory=list)

    def pull(self, *, subscription: str, max_messages: int) -> Result[list[ReceivedMessage]]:
        if self.pull_error:
            return err(self.pull_error)
        return ok(list(self.messages))

    def ack(self, *, subscription: str, ack_ids: Sequence[str]) -> Result[None]:
        self.acked.append(list(ack_ids))
        if self.ack_error:
            return err(self.ack_error)
        return ok(None)


def _pull(conn: sqlite3.Connection, puller: FakePuller) -> PullReport:
    return unwrap(pull_once(conn=conn, puller=puller, subscription=SUBSCRIPTION, now=NOW))


class TestEventFromPubsub:
    def test_builds_a_reaction_event(self) -> None:
        event = event_from_pubsub(message=reaction(number=1))

        assert event is not None
        assert (event.type, event.space, event.sender, event.source) == (
            REACTION_CREATED,
            SPACE,
            "users/111",
            EventSource.PUBSUB,
        )

    def test_keeps_the_reaction_payload(self) -> None:
        event = event_from_pubsub(message=reaction(number=1, event_type=REACTION_DELETED))

        assert event is not None
        assert event.payload["reaction"]["emoji"] == {"unicode": "🤖"}

    def test_falls_back_to_the_publish_time(self) -> None:
        message = reaction(number=1, attributes={"ce-type": REACTION_CREATED}, publish_time=NOW)

        event = event_from_pubsub(message=message)

        assert event is not None
        assert event.event_time == NOW

    @pytest.mark.parametrize(
        "message",
        [
            reaction(number=1, attributes={"ce-type": "google.workspace.chat.message.v1.created"}),
            reaction(number=1, data=b"{not json"),
            reaction(number=1, data=b"\xff"),
            reaction(number=1, data=b'{"reaction": {"name": 7}}'),
            reaction(number=1, data=b'{"reaction": {"name": "spaces/A/messages/m"}}'),
            reaction(number=1, attributes={"ce-type": REACTION_CREATED}),
            reaction(
                number=1,
                attributes={"ce-type": REACTION_CREATED},
                publish_time=datetime(2026, 11, 6, 12, 0),
            ),
        ],
        ids=[
            "message-type",
            "bad-json",
            "not-utf8",
            "name-not-text",
            "not-a-reaction-name",
            "no-time",
            "naive-time",
        ],
    )
    def test_rejects_an_unusable_message(self, message: ReceivedMessage) -> None:
        assert event_from_pubsub(message=message) is None


class TestPullOnce:
    def test_stores_and_acks_each_event(self, conn: sqlite3.Connection) -> None:
        puller = FakePuller(messages=[reaction(number=1), reaction(number=2, space=OTHER)])

        report = _pull(conn, puller)

        assert (report.pulled, report.inserted, report.acked) == (2, 2, 2)
        assert (
            conn.execute("SELECT COUNT(*) FROM events WHERE source = 'pubsub'").fetchone()[0] == 2
        )

    def test_remembers_a_created_reaction_for_backfill(self, conn: sqlite3.Connection) -> None:
        _pull(conn, FakePuller(messages=[reaction(number=1)]))

        rows = conn.execute("SELECT reaction_name, emoji, user FROM reaction_snapshot").fetchall()

        assert [tuple(row) for row in rows] == [
            (f"{SPACE}/messages/m001/reactions/r001", "🤖", "users/111")
        ]

    def test_forgets_a_deleted_reaction(self, conn: sqlite3.Connection) -> None:
        _pull(conn, FakePuller(messages=[reaction(number=1)]))

        _pull(conn, FakePuller(messages=[reaction(number=1, event_type=REACTION_DELETED)]))

        assert conn.execute("SELECT COUNT(*) FROM reaction_snapshot").fetchone()[0] == 0

    def test_a_redelivery_lands_once(self, conn: sqlite3.Connection) -> None:
        puller = FakePuller(messages=[reaction(number=1)])
        _pull(conn, puller)

        report = _pull(conn, puller)

        assert (report.inserted, report.duplicates, report.acked) == (0, 1, 1)

    def test_a_push_delivery_is_never_lookback(self, conn: sqlite3.Connection) -> None:
        _pull(conn, FakePuller(messages=[reaction(number=1)]))

        assert conn.execute("SELECT via_lookback FROM events").fetchone()[0] == 0

    def test_acks_an_unusable_message_so_it_is_not_redelivered(
        self, conn: sqlite3.Connection
    ) -> None:
        puller = FakePuller(messages=[reaction(number=1, data=b"{not json")])

        report = _pull(conn, puller)

        assert (report.malformed, report.acked, puller.acked) == (1, 1, [["ack-A1"]])

    def test_leaves_a_failed_space_unacked(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE TRIGGER refuse BEFORE INSERT ON events "
            f"WHEN NEW.space = '{OTHER}' BEGIN SELECT RAISE(ABORT, 'full'); END"
        )
        puller = FakePuller(messages=[reaction(number=1), reaction(number=2, space=OTHER)])

        report = _pull(conn, puller)

        assert (report.failed_spaces, puller.acked) == ((OTHER,), [["ack-A1"]])

    def test_an_ack_failure_reports_nothing_acked(self, conn: sqlite3.Connection) -> None:
        report = _pull(conn, FakePuller(messages=[reaction(number=1)], ack_error="HTTP 503"))

        assert (report.inserted, report.acked) == (1, 0)

    def test_an_empty_pull_sends_no_ack(self, conn: sqlite3.Connection) -> None:
        puller = FakePuller()

        report = _pull(conn, puller)

        assert (report.pulled, puller.acked) == (0, [])

    def test_a_pull_failure_is_returned(self, conn: sqlite3.Connection) -> None:
        result = pull_once(
            conn=conn, puller=FakePuller(pull_error="HTTP 403"), subscription=SUBSCRIPTION, now=NOW
        )

        assert expect_error(result).error == "HTTP 403"


@dataclass
class FakeSubscriptionApi:
    live: SubscriptionState | None = None
    fail: frozenset[str] = frozenset()
    calls: list[str] = field(default_factory=list)

    def _answer(self, *, call: str, name: str) -> Result[SubscriptionState]:
        self.calls.append(call)
        if call in self.fail:
            return err(f"{call} failed")
        return ok(
            SubscriptionState(name=name, state="ACTIVE", expire_time=NOW + timedelta(hours=4))
        )

    def get(self, *, name: str) -> Result[SubscriptionState | None]:
        self.calls.append("get")
        if "get" in self.fail:
            return err("get failed")
        return ok(self.live)

    def create(self, *, spec: SubscriptionSpec) -> Result[SubscriptionState]:
        return self._answer(call="create", name=NEW)

    def renew(self, *, name: str) -> Result[SubscriptionState]:
        return self._answer(call="renew", name=name)

    def reactivate(self, *, name: str) -> Result[SubscriptionState]:
        return self._answer(call="reactivate", name=name)


def _store_old(conn: sqlite3.Connection) -> None:
    api = FakeSubscriptionApi()
    api.create = lambda *, spec: ok(  # type: ignore[method-assign]
        SubscriptionState(name=OLD, state="ACTIVE", expire_time=NOW + timedelta(hours=4))
    )
    unwrap(ensure_subscription(conn=conn, api=api, spec=SPEC, now=NOW - timedelta(hours=5)))


def _live(
    *, state: str = "ACTIVE", expires_in: timedelta = timedelta(hours=3)
) -> SubscriptionState:
    return SubscriptionState(name=OLD, state=state, expire_time=NOW + expires_in)


class TestEnsureSubscription:
    def test_creates_one_when_none_is_stored(self, conn: sqlite3.Connection) -> None:
        api = FakeSubscriptionApi()

        status = unwrap(ensure_subscription(conn=conn, api=api, spec=SPEC, now=NOW))

        assert (status.action, api.calls) == (RenewalAction.CREATED, ["create"])

    def test_records_the_subscription(self, conn: sqlite3.Connection) -> None:
        unwrap(ensure_subscription(conn=conn, api=FakeSubscriptionApi(), spec=SPEC, now=NOW))

        stored = get_subscription(conn=conn, target=ALL_SPACES)

        assert stored is not None
        assert (stored.name, stored.renewed_at) == (NEW, NOW)

    @pytest.mark.parametrize(
        ("live", "action", "calls"),
        [
            (_live(), RenewalAction.RENEWED, ["get", "renew"]),
            (None, RenewalAction.RECREATED, ["get", "create"]),
            (_live(expires_in=timedelta(0)), RenewalAction.RECREATED, ["get", "create"]),
            (_live(state="DELETED"), RenewalAction.RECREATED, ["get", "create"]),
            (_live(state="SUSPENDED"), RenewalAction.REACTIVATED, ["get", "reactivate"]),
        ],
        ids=["active", "lapsed", "expired", "deleted", "suspended"],
    )
    def test_refreshes_the_stored_subscription(
        self,
        conn: sqlite3.Connection,
        live: SubscriptionState | None,
        action: RenewalAction,
        calls: list[str],
    ) -> None:
        _store_old(conn)
        api = FakeSubscriptionApi(live=live)

        status = unwrap(ensure_subscription(conn=conn, api=api, spec=SPEC, now=NOW))

        assert (status.action, api.calls) == (action, calls)

    def test_a_lapsed_subscription_is_replaced_in_the_store(
        self, conn: sqlite3.Connection
    ) -> None:
        _store_old(conn)

        status = unwrap(
            ensure_subscription(conn=conn, api=FakeSubscriptionApi(), spec=SPEC, now=NOW)
        )

        stored = get_subscription(conn=conn, target=ALL_SPACES)
        assert stored is not None
        assert status == SubscriptionStatus(
            name=NEW, expire_time=NOW + timedelta(hours=4), action=RenewalAction.RECREATED
        )
        assert stored.name == NEW

    @pytest.mark.parametrize(
        ("live", "failing"),
        [
            (_live(), "get"),
            (_live(), "renew"),
            (None, "create"),
            (_live(state="SUSPENDED"), "reactivate"),
        ],
    )
    def test_an_api_failure_is_returned(
        self,
        conn: sqlite3.Connection,
        live: SubscriptionState | None,
        failing: str,
    ) -> None:
        _store_old(conn)
        api = FakeSubscriptionApi(live=live, fail=frozenset({failing}))

        result = ensure_subscription(conn=conn, api=api, spec=SPEC, now=NOW)

        assert expect_error(result).error == f"{failing} failed"

    def test_a_first_create_failure_is_returned(self, conn: sqlite3.Connection) -> None:
        api = FakeSubscriptionApi(fail=frozenset({"create"}))

        result = ensure_subscription(conn=conn, api=api, spec=SPEC, now=NOW)

        assert isinstance(result, ErrorResult)

    def test_a_store_failure_is_returned(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE TRIGGER refuse BEFORE INSERT ON subscriptions "
            "BEGIN SELECT RAISE(ABORT, 'full'); END"
        )

        result = ensure_subscription(conn=conn, api=FakeSubscriptionApi(), spec=SPEC, now=NOW)

        assert "full" in expect_error(result).error


class TestRenewalDue:
    @pytest.fixture
    def renewed(self, conn: sqlite3.Connection) -> sqlite3.Connection:
        unwrap(ensure_subscription(conn=conn, api=FakeSubscriptionApi(), spec=SPEC, now=NOW))
        return conn

    def test_due_when_nothing_is_stored(self, conn: sqlite3.Connection) -> None:
        assert renewal_due(conn=conn, target=ALL_SPACES, now=NOW) is True

    @pytest.mark.parametrize(
        ("later", "due"),
        [
            (timedelta(minutes=59), False),
            (timedelta(hours=1), True),
            (timedelta(hours=4), True),
        ],
    )
    def test_due_hourly(self, renewed: sqlite3.Connection, later: timedelta, due: bool) -> None:
        assert renewal_due(conn=renewed, target=ALL_SPACES, now=NOW + later) is due

    def test_due_once_expired_even_if_recently_renewed(self, renewed: sqlite3.Connection) -> None:
        later = NOW + timedelta(hours=5)

        assert renewal_due(conn=renewed, target=ALL_SPACES, now=later, every=timedelta(days=1))
