"""The reactions the bus has seen, kept so backfill can infer deletions (ADR-0035 D7).

The Chat API lists the reactions a message has now, never the ones it
lost. Every source that stores a reaction event records it here, so a
reaction seen live and removed during a sleep is missing from the next
listing and backfill can synthesize its ``reaction.deleted``.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from dev10x.comm.chatbus.events import REACTION_CREATED, REACTION_DELETED, ChatEvent, to_db_time
from dev10x.comm.chatbus.store import write_transaction
from dev10x.domain.common.result import Result, err, ok

log = logging.getLogger(__name__)

CUSTOM_EMOJI_PREFIX = "customEmoji/"


@dataclass(frozen=True)
class SnapshotReaction:
    name: str
    message: str
    emoji: str
    user: str


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def emoji_key(*, emoji: object) -> str | None:
    """One stable text key per emoji; a custom emoji's image URI changes, its uid does not."""
    raw = _mapping(emoji)
    unicode = raw.get("unicode")
    if isinstance(unicode, str) and unicode:
        return unicode
    uid = _mapping(raw.get("customEmoji")).get("uid")
    if isinstance(uid, str) and uid:
        return f"{CUSTOM_EMOJI_PREFIX}{uid}"
    return None


def emoji_resource(*, key: str) -> dict[str, Any]:
    if key.startswith(CUSTOM_EMOJI_PREFIX):
        return {"customEmoji": {"uid": key.removeprefix(CUSTOM_EMOJI_PREFIX)}}
    return {"unicode": key}


def reaction_summary(*, message: Mapping[str, Any]) -> dict[str, int]:
    """A listed message's ``emojiReactionSummaries`` as emoji key to count."""
    summary: dict[str, int] = {}
    entries = message.get("emojiReactionSummaries")
    for entry in entries if isinstance(entries, list) else []:
        key = emoji_key(emoji=_mapping(entry).get("emoji"))
        count = _mapping(entry).get("reactionCount")
        if key is not None and isinstance(count, int) and count > 0:
            summary[key] = summary.get(key, 0) + count
    return summary


def parse_reaction(*, raw: Mapping[str, Any], message: str) -> SnapshotReaction | None:
    """A listed reaction resource, or None when it does not belong to ``message``."""
    name = raw.get("name")
    user = _mapping(raw.get("user")).get("name")
    key = emoji_key(emoji=raw.get("emoji"))
    if not isinstance(name, str) or not name.startswith(f"{message}/reactions/"):
        return None
    if not isinstance(user, str) or not user or key is None:
        return None
    return SnapshotReaction(name=name, message=message, emoji=key, user=user)


def get_snapshot(*, conn: sqlite3.Connection, message: str) -> dict[str, SnapshotReaction]:
    rows = conn.execute(
        "SELECT reaction_name, emoji, user FROM reaction_snapshot WHERE message_name = ?",
        (message,),
    ).fetchall()
    return {
        row[0]: SnapshotReaction(name=row[0], message=message, emoji=row[1], user=row[2])
        for row in rows
    }


def snapshot_summary(*, conn: sqlite3.Connection, message: str) -> dict[str, int]:
    summary: dict[str, int] = {}
    for reaction in get_snapshot(conn=conn, message=message).values():
        summary[reaction.emoji] = summary.get(reaction.emoji, 0) + 1
    return summary


def _from_event(*, event: ChatEvent) -> SnapshotReaction | None:
    message = event.resource_name.rsplit("/reactions/", 1)[0]
    return parse_reaction(raw=_mapping(event.payload.get("reaction")), message=message)


def remember_reactions(
    *,
    conn: sqlite3.Connection,
    events: Sequence[ChatEvent],
    now: datetime,
) -> Result[int]:
    """Apply stored reaction events to the snapshot, in event order.

    Run it after the events are committed. A crash in between leaves the
    snapshot behind; the next backfill re-diffs, and ingest dedupes the
    repeated events.
    """
    stamp = to_db_time(moment=now)
    applied = 0
    try:
        with write_transaction(conn=conn) as tx:
            for event in sorted(events, key=lambda candidate: candidate.position):
                if event.type == REACTION_DELETED:
                    tx.execute(
                        "DELETE FROM reaction_snapshot WHERE reaction_name = ?",
                        (event.resource_name,),
                    )
                    applied += 1
                    continue
                reaction = _from_event(event=event) if event.type == REACTION_CREATED else None
                if reaction is None:
                    continue
                tx.execute(
                    """
                    INSERT INTO reaction_snapshot
                        (reaction_name, message_name, emoji, user, seen_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT (reaction_name) DO UPDATE SET seen_at = excluded.seen_at
                    """,
                    (reaction.name, reaction.message, reaction.emoji, reaction.user, stamp),
                )
                applied += 1
    except sqlite3.Error as exc:
        log.error("Cannot update the Chat bus reaction snapshot: %s", exc)
        return err(f"Cannot update the Chat bus reaction snapshot: {exc}")
    return ok(applied)
