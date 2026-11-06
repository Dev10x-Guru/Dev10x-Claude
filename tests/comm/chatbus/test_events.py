from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from dev10x.comm.chatbus.events import MESSAGE_CREATED, ChatEvent, EventSource, to_db_time
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
