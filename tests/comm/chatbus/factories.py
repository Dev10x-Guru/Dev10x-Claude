from __future__ import annotations

from datetime import UTC, datetime, timedelta

from dev10x.comm.chatbus.events import MESSAGE_CREATED, ChatEvent, EventSource

NOW = datetime(2026, 11, 6, 12, 0, 0, tzinfo=UTC)
SPACE = "spaces/AAAA"


def message_event(
    *,
    number: int,
    minutes_ago: int = 0,
    source: EventSource = EventSource.POLL,
    space: str = SPACE,
) -> ChatEvent:
    name = f"{space}/messages/m{number:03d}"
    return ChatEvent(
        type=MESSAGE_CREATED,
        resource_name=name,
        space=space,
        sender="users/111",
        event_time=NOW - timedelta(minutes=minutes_ago),
        payload={"message": {"name": name, "text": f"message {number}"}},
        source=source,
    )
