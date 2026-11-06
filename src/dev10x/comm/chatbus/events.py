from __future__ import annotations

import json
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


class EventSource(StrEnum):
    PUBSUB = "pubsub"
    POLL = "poll"
    BACKFILL = "backfill"


def to_db_time(*, moment: datetime) -> str:
    # Fixed width and UTC, so stored times compare correctly as text.
    if moment.tzinfo is None:
        raise ValueError(f"Chat bus times must be timezone-aware, got {moment!r}")
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


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
        object.__setattr__(self, "db_time", to_db_time(moment=self.event_time))
        object.__setattr__(self, "payload_json", json.dumps(self.payload, sort_keys=True))

    @property
    def event_key(self) -> str:
        return f"{self.type}:{self.resource_name}"

    @property
    def position(self) -> tuple[str, str]:
        return (self.db_time, self.resource_name)
