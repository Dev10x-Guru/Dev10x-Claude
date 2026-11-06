from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from dev10x.comm.chatbus.events import REACTION_DELETED, ChatEvent, EventSource, to_db_time
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
        assert event.event_key == (
            f"google.workspace.chat.message.v1.created:{SPACE}/messages/m007"
        )

    def test_position_orders_by_time_then_name(self, event: ChatEvent) -> None:
        assert event.position == ("2026-11-06T11:59:00.000000Z", f"{SPACE}/messages/m007")


class TestEventTypes:
    def test_deleted_reaction_uses_workspace_events_name(self) -> None:
        assert REACTION_DELETED == "google.workspace.chat.reaction.v1.deleted"
