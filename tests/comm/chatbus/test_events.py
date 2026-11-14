from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from dev10x.comm.chatbus.events import (
    MESSAGE_CREATED,
    REACTION_CREATED,
    REACTION_DELETED,
    ChatEvent,
    EventSource,
    resource_space,
    to_db_time,
)
from tests.comm.chatbus.factories import NOW, SPACE, message_event


class TestToDbTime:
    def test_rejects_naive_datetime(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            to_db_time(moment=datetime(2026, 11, 6, 12, 0, 0))

    def test_formats_fixed_width_utc(self) -> None:
        assert to_db_time(moment=NOW) == "2026-11-06T12:00:00.000000Z"

    def test_normalizes_other_zones_to_utc(self) -> None:
        warsaw = NOW.astimezone(timezone(timedelta(hours=1)))
        assert to_db_time(moment=warsaw) == "2026-11-06T12:00:00.000000Z"


class TestChatEvent:
    @pytest.fixture
    def event(self) -> ChatEvent:
        return message_event(number=7, minutes_ago=1, source=EventSource.BACKFILL)

    def test_event_key_joins_type_and_resource(self, event: ChatEvent) -> None:
        assert event.event_key == f"{MESSAGE_CREATED}:{SPACE}/messages/m007"

    def test_position_orders_by_time_then_name(self, event: ChatEvent) -> None:
        assert event.position == ("2026-11-06T11:59:00.000000Z", f"{SPACE}/messages/m007")

    def test_payload_serialized_with_sorted_keys(self, event: ChatEvent) -> None:
        assert event.payload_json == (
            f'{{"message": {{"name": "{SPACE}/messages/m007", "text": "message 7"}}}}'
        )


def _event(
    *,
    event_time: datetime = NOW,
    payload: dict[str, object] | None = None,
) -> ChatEvent:
    return ChatEvent(
        type=MESSAGE_CREATED,
        resource_name=f"{SPACE}/messages/m001",
        space=SPACE,
        sender="users/111",
        event_time=event_time,
        payload=payload or {},
        source=EventSource.POLL,
    )


class TestRejectedAtConstruction:
    """A source fails on the one bad event it parsed, never later inside an ingest batch."""

    def test_unencodable_payload(self) -> None:
        with pytest.raises(TypeError, match="not JSON serializable"):
            _event(payload={"attachment": object()})

    def test_naive_event_time(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            _event(event_time=datetime(2026, 11, 6, 12, 0, 0))


class TestIdentityFieldsValidated:
    """GH-1839: a malformed event cannot claim a key a genuine event needs."""

    @pytest.mark.parametrize(
        ("event_type", "resource_name", "space", "message"),
        [
            ("google.workspace.chat.space.v1.updated", f"{SPACE}/messages/a", SPACE, "Unknown"),
            (MESSAGE_CREATED, f"{SPACE}/messages/a/reactions/b", SPACE, "Malformed"),
            (REACTION_CREATED, f"{SPACE}/messages/a", SPACE, "Malformed"),
            (REACTION_DELETED, "messages/a/reactions/b", SPACE, "Malformed"),
            (MESSAGE_CREATED, f"{SPACE}/messages/a b", SPACE, "Malformed"),
            (MESSAGE_CREATED, "spaces/BBBB/messages/a", SPACE, "not in the event's space"),
        ],
    )
    def test_rejected(self, event_type: str, resource_name: str, space: str, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            ChatEvent(
                type=event_type,
                resource_name=resource_name,
                space=space,
                sender="users/111",
                event_time=NOW,
                payload={},
                source=EventSource.POLL,
            )


class TestResourceSpace:
    def test_unknown_type(self) -> None:
        assert resource_space(event_type="x", resource_name=f"{SPACE}/messages/a") is None

    def test_reaction(self) -> None:
        name = f"{SPACE}/messages/a/reactions/b"
        assert resource_space(event_type=REACTION_CREATED, resource_name=name) == SPACE
