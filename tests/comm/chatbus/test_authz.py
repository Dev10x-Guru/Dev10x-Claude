from __future__ import annotations

import ast
import logging
import sqlite3
from dataclasses import FrozenInstanceError, dataclass, field
from pathlib import Path
from typing import Any

import pytest
from dev10x.domain.common.result import Result, err, ok

from dev10x.comm.chatbus import authz
from dev10x.comm.chatbus.authz import (
    Allowlist,
    Outcome,
    Verdict,
    authorize,
    build_allowlist,
    load_allowlist,
)
from dev10x.comm.chatbus.events import (
    MESSAGE_CREATED,
    REACTION_CREATED,
    REACTION_DELETED,
    ChatEvent,
    EventSource,
)
from dev10x.comm.chatbus.ingest import ingest_events
from dev10x.comm.skills.notifications import gchat_users
from dev10x.comm.skills.notifications.gchat_users import BusRole, ChatUser
from tests.comm.chatbus.factories import NOW, SPACE, expect_error, unwrap

OWNER = "users/1"
TRUSTED = "users/2"
STRANGER = "users/9"
BOT = "users/500"
DM_SPACE = "spaces/DM01"
APPROVAL_DM = f"{DM_SPACE}/messages/approval1"

ALLOWLIST = Allowlist(
    owner=OWNER,
    trusted=frozenset({TRUSTED}),
    logins={OWNER: "owner-login", TRUSTED: "trusted-login"},
)


@dataclass
class FakeNotifier:
    outcome: Result[str] = field(default_factory=lambda: ok(APPROVAL_DM))
    calls: list[dict[str, Any]] = field(default_factory=list)

    def request_approval(
        self,
        *,
        owner: str,
        work_item_id: int,
        requester: str,
        verb: str,
    ) -> Result[str]:
        self.calls.append(
            {"owner": owner, "work_item_id": work_item_id, "requester": requester, "verb": verb}
        )
        return self.outcome


_counter = iter(range(1, 100_000))


def message(
    *,
    sender: str,
    text: str,
    mention: bool = True,
    direct: bool = False,
    source: EventSource = EventSource.POLL,
    payload_sender: str | None = None,
) -> ChatEvent:
    space = DM_SPACE if direct else SPACE
    name = f"{space}/messages/m{next(_counter)}"
    annotations = (
        [{"type": "USER_MENTION", "userMention": {"user": {"name": BOT, "type": "BOT"}}}]
        if mention
        else []
    )
    resource = {
        "name": name,
        "sender": {"name": payload_sender or sender, "type": "HUMAN"},
        "text": text,
        "argumentText": text,
        "annotations": annotations,
        "space": {"name": space, "spaceType": "DIRECT_MESSAGE" if direct else "SPACE"},
    }
    return ChatEvent(
        type=MESSAGE_CREATED,
        resource_name=name,
        space=space,
        sender=sender,
        event_time=NOW,
        payload={"message": resource},
        source=source,
    )


def reaction(
    *,
    sender: str,
    emoji: str,
    on: str = f"{SPACE}/messages/target",
    source: EventSource = EventSource.PUBSUB,
    event_type: str = REACTION_CREATED,
) -> ChatEvent:
    name = f"{on}/reactions/r{next(_counter)}"
    space = "/".join(on.split("/")[:2])
    return ChatEvent(
        type=event_type,
        resource_name=name,
        space=space,
        sender=sender,
        event_time=NOW,
        payload={
            "reaction": {"name": name, "user": {"name": sender}, "emoji": {"unicode": emoji}}
        },
        source=source,
    )


def store(*, conn: sqlite3.Connection, event: ChatEvent) -> int:
    unwrap(ingest_events(conn=conn, space=event.space, events=[event], now=NOW))
    row = conn.execute("SELECT id FROM events WHERE event_key = ?", (event.event_key,)).fetchone()
    return int(row[0])


def decide(
    *,
    conn: sqlite3.Connection,
    event: ChatEvent,
    notifier: FakeNotifier | None = None,
) -> Verdict:
    return unwrap(
        authorize(
            conn=conn,
            event_id=store(conn=conn, event=event),
            allowlist=ALLOWLIST,
            bot_user=BOT,
            notifier=notifier or FakeNotifier(),
            now=NOW,
        )
    )


def work_items(*, conn: sqlite3.Connection) -> list[tuple[str, str]]:
    rows = conn.execute("SELECT kind, status FROM work_items ORDER BY id").fetchall()
    return [(row[0], row[1]) for row in rows]


def commands(*, conn: sqlite3.Connection) -> list[tuple[str, str, int]]:
    rows = conn.execute("SELECT actor, verb, authorized FROM commands ORDER BY id").fetchall()
    return [(row[0], row[1], row[2]) for row in rows]


class TestAnyoneGetsAReply:
    """D2 row 1: a mention or DM from anyone creates a reply item."""

    @pytest.fixture(params=[OWNER, TRUSTED, STRANGER])
    def sender(self, request: pytest.FixtureRequest) -> str:
        return request.param

    @pytest.fixture(params=[False, True], ids=["mention", "dm"])
    def verdict(
        self, conn: sqlite3.Connection, sender: str, request: pytest.FixtureRequest
    ) -> Verdict:
        return decide(
            conn=conn, event=message(sender=sender, text="what is up?", direct=request.param)
        )

    def test_outcome_is_reply(self, verdict: Verdict) -> None:
        assert verdict.outcome is Outcome.REPLY

    def test_queues_one_reply_item(self, conn: sqlite3.Connection, verdict: Verdict) -> None:
        assert work_items(conn=conn) == [("reply", "queued")]


class TestUnaddressedMessageIsIgnored:
    @pytest.fixture
    def verdict(self, conn: sqlite3.Connection) -> Verdict:
        return decide(conn=conn, event=message(sender=OWNER, text="implement it", mention=False))

    def test_ignored(self, verdict: Verdict) -> None:
        assert verdict.outcome is Outcome.IGNORED

    def test_records_nothing(self, conn: sqlite3.Connection, verdict: Verdict) -> None:
        assert (commands(conn=conn), work_items(conn=conn)) == ([], [])


class TestStrangerIsRejected:
    """D2 row 2: a non-allowlisted reaction or command is a rejected command."""

    @pytest.fixture(
        params=[
            pytest.param(lambda: message(sender=STRANGER, text="implement X"), id="command"),
            pytest.param(lambda: message(sender=STRANGER, text="start X", direct=True), id="dm"),
            pytest.param(lambda: reaction(sender=STRANGER, emoji="🎫"), id="ticket-reaction"),
            pytest.param(lambda: reaction(sender=STRANGER, emoji="🤖"), id="robot-reaction"),
            pytest.param(
                lambda: reaction(sender=STRANGER, emoji="🤖", source=EventSource.BACKFILL),
                id="backfilled-reaction",
            ),
            pytest.param(
                lambda: message(sender=STRANGER, text="ticket this", source=EventSource.BACKFILL),
                id="backfilled-command",
            ),
        ]
    )
    def verdict(self, conn: sqlite3.Connection, request: pytest.FixtureRequest) -> Verdict:
        return decide(conn=conn, event=request.param())

    def test_rejected(self, verdict: Verdict) -> None:
        assert (verdict.outcome, verdict.reason) == (
            Outcome.REJECTED,
            "sender is not on the bus allowlist",
        )

    def test_recorded_unauthorized(self, conn: sqlite3.Connection, verdict: Verdict) -> None:
        assert [row[2] for row in commands(conn=conn)] == [0]

    def test_no_work_item(self, conn: sqlite3.Connection, verdict: Verdict) -> None:
        assert work_items(conn=conn) == []


class TestTrustedCommandAwaitsApproval:
    """D2 row 3: a trusted privileged command waits for the owner."""

    @pytest.fixture
    def notifier(self) -> FakeNotifier:
        return FakeNotifier()

    @pytest.fixture
    def verdict(self, conn: sqlite3.Connection, notifier: FakeNotifier) -> Verdict:
        return decide(
            conn=conn, event=message(sender=TRUSTED, text="implement the thing"), notifier=notifier
        )

    def test_awaiting(self, verdict: Verdict) -> None:
        assert verdict.outcome is Outcome.AWAITING_APPROVAL

    def test_item_awaits(self, conn: sqlite3.Connection, verdict: Verdict) -> None:
        assert work_items(conn=conn) == [("privileged", "awaiting_approval")]

    def test_dm_sent_to_owner(self, notifier: FakeNotifier, verdict: Verdict) -> None:
        assert notifier.calls == [
            {
                "owner": OWNER,
                "work_item_id": verdict.work_item_id,
                "requester": TRUSTED,
                "verb": "implement",
            }
        ]

    def test_dm_recorded(self, conn: sqlite3.Connection, verdict: Verdict) -> None:
        row = conn.execute("SELECT work_item_id, dm_message FROM approvals").fetchone()
        assert (verdict.approval_dm, tuple(row)) == (
            APPROVAL_DM,
            (verdict.work_item_id, APPROVAL_DM),
        )


class TestApprovalDmFailure:
    @pytest.fixture
    def verdict(self, conn: sqlite3.Connection) -> Verdict:
        return decide(
            conn=conn,
            event=message(sender=TRUSTED, text="start a session"),
            notifier=FakeNotifier(outcome=err("chat down")),
        )

    def test_item_still_awaits(self, conn: sqlite3.Connection, verdict: Verdict) -> None:
        assert (verdict.outcome, verdict.approval_dm, work_items(conn=conn)) == (
            Outcome.AWAITING_APPROVAL,
            None,
            [("privileged", "awaiting_approval")],
        )


class TestApprovalDmCannotBeRecorded:
    @pytest.fixture
    def verdict(self, conn: sqlite3.Connection) -> Verdict:
        decide(conn=conn, event=message(sender=TRUSTED, text="start one"))
        # A second request reusing the same DM name violates UNIQUE (dm_message).
        return decide(conn=conn, event=message(sender=TRUSTED, text="start two"))

    def test_item_still_awaits(self, verdict: Verdict) -> None:
        assert (verdict.outcome, verdict.approval_dm) == (Outcome.AWAITING_APPROVAL, None)


class TestTrustedReactionIsRejected:
    @pytest.fixture
    def verdict(self, conn: sqlite3.Connection) -> Verdict:
        return decide(conn=conn, event=reaction(sender=TRUSTED, emoji="🎫"))

    def test_rejected(self, conn: sqlite3.Connection, verdict: Verdict) -> None:
        assert (verdict.outcome, verdict.reason, work_items(conn=conn)) == (
            Outcome.REJECTED,
            "only the owner's reactions trigger work",
            [],
        )


class TestOwnerSignalQueues:
    """D2 row 4: an owner reaction or command queues a privileged item."""

    @pytest.fixture(
        params=[
            pytest.param((lambda: reaction(sender=OWNER, emoji="🎫"), "ticket"), id="ticket"),
            pytest.param((lambda: reaction(sender=OWNER, emoji="🤖"), "start"), id="robot"),
            pytest.param(
                (lambda: message(sender=OWNER, text="Implement the fix"), "implement"),
                id="command",
            ),
            pytest.param(
                (
                    lambda: reaction(sender=OWNER, emoji="🤖", source=EventSource.BACKFILL),
                    "start",
                ),
                id="backfilled",
            ),
        ]
    )
    def case(self, request: pytest.FixtureRequest) -> tuple[ChatEvent, str]:
        build, verb = request.param
        return build(), verb

    @pytest.fixture
    def verdict(self, conn: sqlite3.Connection, case: tuple[ChatEvent, str]) -> Verdict:
        return decide(conn=conn, event=case[0])

    def test_queued(self, verdict: Verdict, case: tuple[ChatEvent, str]) -> None:
        assert (verdict.outcome, verdict.verb) == (Outcome.QUEUED, case[1])

    def test_privileged_item(self, conn: sqlite3.Connection, verdict: Verdict) -> None:
        assert work_items(conn=conn) == [("privileged", "queued")]


class TestOwnerApproval:
    """D2 row 5: the owner's ✅ or `approve <id>` releases the awaiting item."""

    @pytest.fixture
    def awaiting(self, conn: sqlite3.Connection) -> Verdict:
        return decide(conn=conn, event=message(sender=TRUSTED, text="implement X"))

    @pytest.fixture(params=["reaction", "command"])
    def verdict(
        self, conn: sqlite3.Connection, awaiting: Verdict, request: pytest.FixtureRequest
    ) -> Verdict:
        events = {
            "reaction": lambda: reaction(sender=OWNER, emoji="✅", on=APPROVAL_DM),
            "command": lambda: message(
                sender=OWNER, text=f"approve {awaiting.work_item_id}", direct=True
            ),
        }
        return decide(conn=conn, event=events[request.param]())

    def test_approved(self, awaiting: Verdict, verdict: Verdict) -> None:
        assert (verdict.outcome, verdict.work_item_id) == (
            Outcome.APPROVED,
            awaiting.work_item_id,
        )

    def test_item_queued(self, conn: sqlite3.Connection, verdict: Verdict) -> None:
        assert work_items(conn=conn) == [("privileged", "queued")]

    def test_approval_recorded(self, conn: sqlite3.Connection, verdict: Verdict) -> None:
        row = conn.execute("SELECT approved_by_event, approved_at FROM approvals").fetchone()
        assert (row[0], row[1]) == (verdict.event_id, "2026-11-06T12:00:00.000000Z")


class TestApprovalRefused:
    @pytest.fixture
    def awaiting(self, conn: sqlite3.Connection) -> Verdict:
        return decide(conn=conn, event=message(sender=TRUSTED, text="implement X"))

    @pytest.fixture(
        params=[
            pytest.param(
                (TRUSTED, "dm-command", "only the owner approves privileged work"),
                id="trusted-command",
            ),
            pytest.param(
                (TRUSTED, "reaction", "only the owner approves privileged work"),
                id="trusted-reaction",
            ),
            pytest.param(
                (STRANGER, "reaction", "only the owner approves privileged work"),
                id="stranger-reaction",
            ),
            pytest.param(
                (STRANGER, "dm-command", "only the owner approves privileged work"),
                id="stranger-command",
            ),
            pytest.param(
                (OWNER, "space-command", "approvals count only in a DM with the bot"),
                id="owner-outside-dm",
            ),
            pytest.param((OWNER, "bare", "approve takes one work item id"), id="owner-missing-id"),
            pytest.param(
                (OWNER, "not-a-number", "approve takes one work item id"), id="owner-bad-id"
            ),
            pytest.param(
                (OWNER, "unicode-digit", "approve takes one work item id"),
                id="owner-unicode-digit",
            ),
        ]
    )
    def case(self, awaiting: Verdict, request: pytest.FixtureRequest) -> tuple[ChatEvent, str]:
        sender, shape, reason = request.param
        item = awaiting.work_item_id
        events = {
            "dm-command": lambda: message(sender=sender, text=f"approve {item}", direct=True),
            "space-command": lambda: message(sender=sender, text=f"approve {item}"),
            "reaction": lambda: reaction(sender=sender, emoji="✅", on=APPROVAL_DM),
            "bare": lambda: message(sender=sender, text="approve", direct=True),
            "not-a-number": lambda: message(sender=sender, text="approve it", direct=True),
            "unicode-digit": lambda: message(sender=sender, text="approve ²", direct=True),
        }
        return events[shape](), reason

    @pytest.fixture
    def verdict(self, conn: sqlite3.Connection, case: tuple[ChatEvent, str]) -> Verdict:
        return decide(conn=conn, event=case[0])

    def test_rejected(self, verdict: Verdict, case: tuple[ChatEvent, str]) -> None:
        assert (verdict.outcome, verdict.reason) == (Outcome.REJECTED, case[1])

    def test_item_keeps_waiting(self, conn: sqlite3.Connection, verdict: Verdict) -> None:
        assert work_items(conn=conn) == [("privileged", "awaiting_approval")]


class TestApprovingAnItemThatIsNotWaiting:
    @pytest.fixture
    def reply_item(self, conn: sqlite3.Connection) -> Verdict:
        return decide(conn=conn, event=message(sender=STRANGER, text="hello"))

    @pytest.fixture
    def verdict(self, conn: sqlite3.Connection, reply_item: Verdict) -> Verdict:
        return decide(
            conn=conn,
            event=message(sender=OWNER, text=f"approve {reply_item.work_item_id}", direct=True),
        )

    def test_rejected(self, verdict: Verdict, reply_item: Verdict) -> None:
        assert (verdict.outcome, verdict.reason) == (
            Outcome.REJECTED,
            f"work item {reply_item.work_item_id} is not awaiting approval",
        )

    def test_reply_item_untouched(self, conn: sqlite3.Connection, verdict: Verdict) -> None:
        assert work_items(conn=conn) == [("reply", "queued")]


class TestIgnoredEvents:
    @pytest.fixture(
        params=[
            pytest.param(lambda: reaction(sender=OWNER, emoji="✅"), id="check-elsewhere"),
            pytest.param(lambda: reaction(sender=OWNER, emoji="👍"), id="other-emoji"),
            pytest.param(
                lambda: reaction(sender=OWNER, emoji="🎫", event_type=REACTION_DELETED),
                id="reaction-removed",
            ),
            pytest.param(lambda: message(sender=BOT, text="implement", direct=True), id="bot"),
        ]
    )
    def verdict(self, conn: sqlite3.Connection, request: pytest.FixtureRequest) -> Verdict:
        return decide(conn=conn, event=request.param())

    def test_ignored(self, verdict: Verdict) -> None:
        assert verdict.outcome is Outcome.IGNORED

    def test_records_nothing(self, conn: sqlite3.Connection, verdict: Verdict) -> None:
        assert (commands(conn=conn), work_items(conn=conn)) == ([], [])


def bare_message(*, sender: str, resource: dict[str, Any]) -> ChatEvent:
    name = f"{DM_SPACE}/messages/bare{next(_counter)}"
    return ChatEvent(
        type=MESSAGE_CREATED,
        resource_name=name,
        space=DM_SPACE,
        sender=sender,
        event_time=NOW,
        payload={"message": {"name": name, "sender": {"name": sender}, **resource}},
        source=EventSource.POLL,
    )


class TestMessageShapes:
    @pytest.mark.parametrize(
        ("resource", "outcome", "verb"),
        [
            pytest.param({}, Outcome.IGNORED, "", id="no-space-no-annotations"),
            pytest.param(
                {"space": {"type": "DM"}, "text": "ticket it"},
                Outcome.QUEUED,
                "ticket",
                id="legacy-dm-text-fallback",
            ),
            pytest.param(
                {"space": {"spaceType": "DIRECT_MESSAGE"}}, Outcome.REPLY, "reply", id="no-text"
            ),
            pytest.param(
                {"annotations": [{"type": "USER_MENTION", "userMention": "x"}]},
                Outcome.IGNORED,
                "",
                id="malformed-mention",
            ),
        ],
    )
    def test_outcome(
        self,
        conn: sqlite3.Connection,
        resource: dict[str, Any],
        outcome: Outcome,
        verb: str,
    ) -> None:
        verdict = decide(conn=conn, event=bare_message(sender=OWNER, resource=resource))
        assert (verdict.outcome, verdict.verb) == (outcome, verb)


class TestIdentityComesFromThePayload:
    """GH-1839 carry-over: a row whose fields disagree with its payload is never trusted."""

    @pytest.fixture(
        params=[
            pytest.param(
                lambda: message(sender=OWNER, text="implement X", payload_sender=STRANGER),
                id="message-sender",
            ),
            pytest.param(
                lambda: ChatEvent(
                    type=REACTION_CREATED,
                    resource_name=f"{SPACE}/messages/x/reactions/spoof",
                    space=SPACE,
                    sender=OWNER,
                    event_time=NOW,
                    payload={
                        "reaction": {
                            "name": f"{SPACE}/messages/x/reactions/spoof",
                            "user": {"name": STRANGER},
                            "emoji": {"unicode": "🎫"},
                        }
                    },
                    source=EventSource.BACKFILL,
                ),
                id="reaction-user",
            ),
            pytest.param(
                lambda: ChatEvent(
                    type=REACTION_CREATED,
                    resource_name=f"{SPACE}/messages/x/reactions/other",
                    space=SPACE,
                    sender=OWNER,
                    event_time=NOW,
                    payload={
                        "reaction": {
                            "name": f"{SPACE}/messages/y/reactions/other",
                            "user": {"name": OWNER},
                            "emoji": {"unicode": "🎫"},
                        }
                    },
                    source=EventSource.PUBSUB,
                ),
                id="resource-name",
            ),
            pytest.param(
                lambda: ChatEvent(
                    type=MESSAGE_CREATED,
                    resource_name=f"{SPACE}/messages/empty",
                    space=SPACE,
                    sender=OWNER,
                    event_time=NOW,
                    payload={},
                    source=EventSource.POLL,
                ),
                id="no-resource",
            ),
        ]
    )
    def verdict(self, conn: sqlite3.Connection, request: pytest.FixtureRequest) -> Verdict:
        return decide(conn=conn, event=request.param())

    def test_rejected(self, conn: sqlite3.Connection, verdict: Verdict) -> None:
        assert (verdict.outcome, work_items(conn=conn)) == (Outcome.REJECTED, [])


def _raw_event(
    *,
    conn: sqlite3.Connection,
    event_type: str,
    resource_name: str,
    payload: str,
) -> int:
    row = conn.execute(
        """
        INSERT INTO events (event_key, type, space, resource_name, sender, event_time,
                            received_at, source, payload)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'poll', ?) RETURNING id
        """,
        (
            f"{event_type}:{resource_name}",
            event_type,
            SPACE,
            resource_name,
            OWNER,
            "2026-11-06T12:00:00.000000Z",
            "2026-11-06T12:00:00.000000Z",
            payload,
        ),
    ).fetchone()
    return int(row[0])


class TestStoredRowsAreRecheckedOnRead:
    """A row written around ChatEvent's checks still fails closed."""

    @pytest.fixture(
        params=[
            pytest.param(("bogus.type", f"{SPACE}/messages/a", "{}"), id="unknown-type"),
            pytest.param((MESSAGE_CREATED, "spaces/OTHER/messages/a", "{}"), id="other-space"),
            pytest.param((MESSAGE_CREATED, f"{SPACE}/messages/a", "not json"), id="bad-json"),
        ]
    )
    def verdict(self, conn: sqlite3.Connection, request: pytest.FixtureRequest) -> Verdict:
        event_type, name, payload = request.param
        event_id = _raw_event(
            conn=conn, event_type=event_type, resource_name=name, payload=payload
        )
        return unwrap(
            authorize(
                conn=conn,
                event_id=event_id,
                allowlist=ALLOWLIST,
                bot_user=BOT,
                notifier=FakeNotifier(),
                now=NOW,
            )
        )

    def test_rejected(self, verdict: Verdict) -> None:
        assert verdict.outcome is Outcome.REJECTED


class TestReplayReturnsTheFirstVerdict:
    @pytest.fixture
    def verdicts(self, conn: sqlite3.Connection) -> tuple[Verdict, Verdict]:
        notifier = FakeNotifier()
        event_id = store(conn=conn, event=message(sender=TRUSTED, text="implement X"))

        def run() -> Verdict:
            return unwrap(
                authorize(
                    conn=conn,
                    event_id=event_id,
                    allowlist=ALLOWLIST,
                    bot_user=BOT,
                    notifier=notifier,
                    now=NOW,
                )
            )

        return run(), run()

    def test_same_outcome(self, verdicts: tuple[Verdict, Verdict]) -> None:
        first, second = verdicts
        assert (second.outcome, second.work_item_id, second.replayed) == (
            first.outcome,
            first.work_item_id,
            True,
        )

    def test_decided_once(
        self, conn: sqlite3.Connection, verdicts: tuple[Verdict, Verdict]
    ) -> None:
        assert (len(commands(conn=conn)), len(work_items(conn=conn))) == (1, 1)


class TestAuthorizeErrors:
    def test_unknown_event(self, conn: sqlite3.Connection) -> None:
        result = authorize(
            conn=conn,
            event_id=404,
            allowlist=ALLOWLIST,
            bot_user=BOT,
            notifier=FakeNotifier(),
            now=NOW,
        )
        assert expect_error(result).error == "No Chat bus event 404"

    def test_closed_connection(self, conn: sqlite3.Connection) -> None:
        event_id = store(conn=conn, event=message(sender=OWNER, text="hi"))
        conn.close()
        result = authorize(
            conn=conn,
            event_id=event_id,
            allowlist=ALLOWLIST,
            bot_user=BOT,
            notifier=FakeNotifier(),
            now=NOW,
        )
        assert expect_error(result).details == {"event_id": event_id}


class TestBuildAllowlist:
    def test_one_owner(self) -> None:
        allowlist = unwrap(
            build_allowlist(
                users=[
                    ChatUser(login="a", chat_user=OWNER, bus_role=BusRole.OWNER),
                    ChatUser(login="b", chat_user=TRUSTED, bus_role=BusRole.TRUSTED),
                    ChatUser(login="b2", chat_user=TRUSTED, bus_role=BusRole.TRUSTED),
                    ChatUser(login="c", chat_user=STRANGER, bus_role=None),
                    ChatUser(login="d", chat_user=None, bus_role=BusRole.OWNER),
                ]
            )
        )
        assert allowlist == Allowlist(
            owner=OWNER, trusted=frozenset({TRUSTED}), logins={OWNER: "a", TRUSTED: "b"}
        )

    @pytest.mark.parametrize(
        "users",
        [
            pytest.param([], id="nobody"),
            pytest.param(
                [ChatUser(login="t", chat_user=TRUSTED, bus_role=BusRole.TRUSTED)],
                id="no-owner",
            ),
            pytest.param(
                [
                    ChatUser(login="a", chat_user=OWNER, bus_role=BusRole.OWNER),
                    ChatUser(login="b", chat_user=TRUSTED, bus_role=BusRole.OWNER),
                ],
                id="two-owners",
            ),
        ],
    )
    def test_refuses_without_exactly_one_owner(self, users: list[ChatUser]) -> None:
        assert (
            "exactly one user with bus_role: owner"
            in expect_error(build_allowlist(users=users)).error
        )

    def test_refuses_conflicting_roles(self) -> None:
        result = build_allowlist(
            users=[
                ChatUser(login="a", chat_user=OWNER, bus_role=BusRole.OWNER),
                ChatUser(login="alias", chat_user=OWNER, bus_role=BusRole.TRUSTED),
            ]
        )
        assert expect_error(result).details == {"chat_user": OWNER}


class TestAllowlist:
    @pytest.mark.parametrize(
        ("sender", "role"),
        [(OWNER, BusRole.OWNER), (TRUSTED, BusRole.TRUSTED), (STRANGER, None)],
    )
    def test_role_of(self, sender: str, role: BusRole | None) -> None:
        assert ALLOWLIST.role_of(sender=sender) is role

    def test_describe(self) -> None:
        assert ALLOWLIST.describe() == (
            "owner=owner-login (users/1); trusted=trusted-login (users/2)"
        )

    def test_describe_without_trusted(self) -> None:
        allowlist = Allowlist(owner=OWNER, trusted=frozenset(), logins={})
        assert allowlist.describe() == "owner=? (users/1); trusted=none"

    def test_is_frozen(self) -> None:
        with pytest.raises(FrozenInstanceError):
            ALLOWLIST.owner = STRANGER  # type: ignore[misc]


CONFIG = """
users:
  boss:
    chat_user_id: "1"
    bus_role: owner
  helper:
    chat_user_id: 2
    bus_role: trusted
  reviewer:
    chat_user_id: "3"
"""


class TestLoadAllowlist:
    @pytest.fixture
    def config(self, tmp_path: Path) -> Path:
        path = tmp_path / "gchat-config.yaml"
        path.write_text(CONFIG)
        return path

    def test_loads_and_logs(self, config: Path, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO, logger=authz.__name__):
            allowlist = unwrap(load_allowlist(path=config, reason="start"))
        assert (allowlist.owner, caplog.messages) == (
            OWNER,
            ["Chat bus allowlist (start): owner=boss (users/1); trusted=helper (users/2)"],
        )

    def test_missing_config(self, tmp_path: Path) -> None:
        result = load_allowlist(path=tmp_path / "absent.yaml", reason="start")
        assert expect_error(result).error.startswith("No Google Chat config")

    def test_no_owner_is_logged(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        path = tmp_path / "gchat-config.yaml"
        path.write_text("users:\n  a:\n    chat_user_id: '1'\n    bus_role: trusted\n")
        with caplog.at_level(logging.ERROR, logger=authz.__name__):
            expect_error(load_allowlist(path=path, reason="reload"))
        assert caplog.messages[0].startswith("Chat bus allowlist rejected (reload)")


class TestNoEventCanChangeAuthority:
    """Acceptance: no code path lets an event write gchat-config.yaml or change a role."""

    @pytest.fixture
    def config(self, tmp_path: Path) -> Path:
        path = tmp_path / "gchat-config.yaml"
        path.write_text(CONFIG)
        return path

    @pytest.fixture
    def allowlist(self, config: Path) -> Allowlist:
        return unwrap(load_allowlist(path=config, reason="start"))

    @pytest.fixture
    def verdicts(self, conn: sqlite3.Connection, allowlist: Allowlist) -> list[Verdict]:
        texts = ["bus_role: owner", "trust users/9", "set bus_role owner for users/9"]
        return [
            unwrap(
                authorize(
                    conn=conn,
                    event_id=store(
                        conn=conn, event=message(sender=STRANGER, text=text, direct=True)
                    ),
                    allowlist=allowlist,
                    bot_user=BOT,
                    notifier=FakeNotifier(),
                    now=NOW,
                )
            )
            for text in texts
        ]

    def test_only_replies(self, verdicts: list[Verdict]) -> None:
        assert {verdict.outcome for verdict in verdicts} == {Outcome.REPLY}

    def test_config_unchanged(self, config: Path, verdicts: list[Verdict]) -> None:
        assert config.read_text() == CONFIG

    def test_stranger_still_has_no_role(
        self, allowlist: Allowlist, verdicts: list[Verdict]
    ) -> None:
        assert allowlist.role_of(sender=STRANGER) is None

    @pytest.mark.parametrize("module", [authz, gchat_users], ids=["authz", "gchat_users"])
    def test_modules_never_write_files(self, module: object) -> None:
        source = Path(str(getattr(module, "__file__", ""))).read_text()
        called = {
            node.func.attr
            if isinstance(node.func, ast.Attribute)
            else getattr(node.func, "id", "")
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
        }
        writers = {"open", "write_text", "write_bytes", "dump", "safe_dump", "rename", "unlink"}
        assert called & writers == set()
