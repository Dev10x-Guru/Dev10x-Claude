from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from dev10x.comm.chatbus.events import (
    REACTION_CREATED,
    REACTION_DELETED,
    ChatEvent,
    EventSource,
)
from dev10x.comm.chatbus.snapshot import (
    SnapshotReaction,
    emoji_key,
    emoji_resource,
    get_snapshot,
    parse_reaction,
    reaction_summary,
    remember_reactions,
    snapshot_summary,
)
from tests.comm.chatbus.factories import NOW, SPACE, expect_error, message_event, unwrap

MESSAGE = f"{SPACE}/messages/m001"
REACTION = f"{MESSAGE}/reactions/r001"


def reaction_event(
    *,
    event_type: str = REACTION_CREATED,
    name: str = REACTION,
    payload: dict[str, Any] | None = None,
) -> ChatEvent:
    return ChatEvent(
        type=event_type,
        resource_name=name,
        space=SPACE,
        sender="users/111",
        event_time=NOW,
        payload={
            "reaction": {"name": name, "user": {"name": "users/111"}, "emoji": {"unicode": "🤖"}}
        }
        if payload is None
        else payload,
        source=EventSource.PUBSUB,
    )


class TestEmojiKey:
    @pytest.mark.parametrize(
        ("emoji", "expected"),
        [
            ({"unicode": "🤖"}, "🤖"),
            ({"customEmoji": {"uid": "abc", "temporaryImageUri": "x"}}, "customEmoji/abc"),
            ({"unicode": ""}, None),
            ({"customEmoji": {}}, None),
            ("🤖", None),
        ],
        ids=["unicode", "custom", "empty-unicode", "custom-without-uid", "not-a-mapping"],
    )
    def test_maps_an_emoji_to_its_key(self, emoji: object, expected: str | None) -> None:
        assert emoji_key(emoji=emoji) == expected

    @pytest.mark.parametrize(
        "emoji",
        [{"unicode": "🤖"}, {"customEmoji": {"uid": "abc"}}],
        ids=["unicode", "custom"],
    )
    def test_a_key_rebuilds_its_emoji(self, emoji: dict[str, Any]) -> None:
        key = emoji_key(emoji=emoji)

        assert key is not None
        assert emoji_resource(key=key) == emoji


class TestReactionSummary:
    def test_counts_reactions_per_emoji(self) -> None:
        message = {
            "emojiReactionSummaries": [
                {"emoji": {"unicode": "🤖"}, "reactionCount": 2},
                {"emoji": {"customEmoji": {"uid": "abc"}}, "reactionCount": 1},
            ]
        }

        assert reaction_summary(message=message) == {"🤖": 2, "customEmoji/abc": 1}

    @pytest.mark.parametrize(
        "summaries",
        [
            None,
            "not-a-list",
            [{"emoji": {"unicode": "🤖"}, "reactionCount": 0}],
            [{"emoji": {}, "reactionCount": 1}],
            [{"emoji": {"unicode": "🤖"}, "reactionCount": "1"}],
        ],
        ids=["missing", "not-a-list", "zero", "no-emoji", "count-not-int"],
    )
    def test_ignores_what_it_cannot_count(self, summaries: object) -> None:
        assert reaction_summary(message={"emojiReactionSummaries": summaries}) == {}


class TestParseReaction:
    def test_parses_a_listed_reaction(self) -> None:
        raw = {"name": REACTION, "user": {"name": "users/111"}, "emoji": {"unicode": "🤖"}}

        assert parse_reaction(raw=raw, message=MESSAGE) == SnapshotReaction(
            name=REACTION, message=MESSAGE, emoji="🤖", user="users/111"
        )

    @pytest.mark.parametrize(
        "raw",
        [
            {"name": f"{SPACE}/messages/m002/reactions/r1", "user": {"name": "users/1"}},
            {"name": 7, "user": {"name": "users/1"}, "emoji": {"unicode": "🤖"}},
            {"name": REACTION, "user": {}, "emoji": {"unicode": "🤖"}},
            {"name": REACTION, "user": {"name": "users/1"}, "emoji": {}},
        ],
        ids=["other-message", "name-not-text", "no-user", "no-emoji"],
    )
    def test_rejects_an_unusable_reaction(self, raw: dict[str, Any]) -> None:
        assert parse_reaction(raw=raw, message=MESSAGE) is None


class TestRememberReactions:
    def test_records_a_created_reaction(self, conn: sqlite3.Connection) -> None:
        applied = unwrap(remember_reactions(conn=conn, events=[reaction_event()], now=NOW))

        assert applied == 1
        assert snapshot_summary(conn=conn, message=MESSAGE) == {"🤖": 1}

    def test_a_deletion_removes_it(self, conn: sqlite3.Connection) -> None:
        unwrap(remember_reactions(conn=conn, events=[reaction_event()], now=NOW))

        unwrap(
            remember_reactions(
                conn=conn, events=[reaction_event(event_type=REACTION_DELETED)], now=NOW
            )
        )

        assert get_snapshot(conn=conn, message=MESSAGE) == {}

    def test_a_repeat_is_harmless(self, conn: sqlite3.Connection) -> None:
        unwrap(remember_reactions(conn=conn, events=[reaction_event()], now=NOW))

        unwrap(remember_reactions(conn=conn, events=[reaction_event()], now=NOW))

        assert snapshot_summary(conn=conn, message=MESSAGE) == {"🤖": 1}

    @pytest.mark.parametrize(
        "event",
        [message_event(number=1), reaction_event(payload={"reaction": {"name": REACTION}})],
        ids=["message", "unusable-reaction"],
    )
    def test_skips_what_is_not_a_reaction(
        self, conn: sqlite3.Connection, event: ChatEvent
    ) -> None:
        assert unwrap(remember_reactions(conn=conn, events=[event], now=NOW)) == 0

    def test_reports_a_store_failure(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE TRIGGER refuse BEFORE INSERT ON reaction_snapshot "
            "BEGIN SELECT RAISE(ABORT, 'full'); END"
        )

        failed = expect_error(remember_reactions(conn=conn, events=[reaction_event()], now=NOW))

        assert "reaction snapshot" in failed.error
