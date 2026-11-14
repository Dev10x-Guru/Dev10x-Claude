from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

# The Workspace Events type names, used verbatim for every source so a
# consumer cannot tell a backfilled event from a Pub/Sub one (ADR-0035 D5).
MESSAGE_CREATED = "google.workspace.chat.message.v1.created"
REACTION_CREATED = "google.workspace.chat.reaction.v1.created"
REACTION_DELETED = "google.workspace.chat.reaction.v1.deleted"

_SEGMENT = r"[A-Za-z0-9_.\-]+"
_MESSAGE_NAME = rf"(?P<space>spaces/{_SEGMENT})/messages/{_SEGMENT}"
_REACTION_NAME = rf"{_MESSAGE_NAME}/reactions/{_SEGMENT}"
# GH-1839: a malformed event must not claim the event_key a genuine one needs.
RESOURCE_NAME_PATTERNS: Mapping[str, re.Pattern[str]] = {
    MESSAGE_CREATED: re.compile(_MESSAGE_NAME),
    REACTION_CREATED: re.compile(_REACTION_NAME),
    REACTION_DELETED: re.compile(_REACTION_NAME),
}
EVENT_TYPES = frozenset(RESOURCE_NAME_PATTERNS)
DB_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def resource_space(*, event_type: str, resource_name: str) -> str | None:
    pattern = RESOURCE_NAME_PATTERNS.get(event_type)
    if pattern is None:
        return None
    match = pattern.fullmatch(resource_name)
    return None if match is None else match["space"]


class EventSource(StrEnum):
    PUBSUB = "pubsub"
    POLL = "poll"
    BACKFILL = "backfill"


def to_db_time(*, moment: datetime) -> str:
    # Fixed width and UTC, so stored times compare correctly as text.
    if moment.tzinfo is None:
        raise ValueError(f"Chat bus times must be timezone-aware, got {moment!r}")
    return moment.astimezone(UTC).strftime(DB_TIME_FORMAT)


def from_db_time(*, value: str) -> datetime:
    return datetime.strptime(value, DB_TIME_FORMAT).replace(tzinfo=UTC)


@dataclass(frozen=True)
class ChatEvent:
    """One Chat event in the Pub/Sub shape.

    Construction rejects what the store cannot hold (a naive time, a
    payload JSON cannot encode), so a source fails on the one bad event
    it parsed instead of failing a whole ingest batch later.
    """

    type: str
    resource_name: str
    space: str
    sender: str
    event_time: datetime
    payload: Mapping[str, Any]
    source: EventSource
    db_time: str = field(init=False, repr=False)
    payload_json: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.type not in EVENT_TYPES:
            raise ValueError(f"Unknown Chat event type {self.type!r}")
        space = resource_space(event_type=self.type, resource_name=self.resource_name)
        if space is None:
            raise ValueError(
                f"Malformed resource name {self.resource_name!r} for a {self.type} event"
            )
        if space != self.space:
            raise ValueError(
                f"Resource {self.resource_name!r} is not in the event's space {self.space!r}"
            )
        object.__setattr__(self, "db_time", to_db_time(moment=self.event_time))
        object.__setattr__(self, "payload_json", json.dumps(self.payload, sort_keys=True))

    @property
    def event_key(self) -> str:
        return f"{self.type}:{self.resource_name}"

    @property
    def position(self) -> tuple[str, str]:
        return (self.db_time, self.resource_name)
