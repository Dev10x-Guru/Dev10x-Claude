from __future__ import annotations

import logging
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from dev10x.comm.chatbus.events import ChatEvent, to_db_time
from dev10x.comm.chatbus.store import write_transaction
from dev10x.domain.common.result import Result, err, ok

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Cursor:
    event_time: str
    resource_name: str

    @classmethod
    def at(cls, *, event_time: datetime, resource_name: str) -> Cursor:
        return cls(event_time=to_db_time(moment=event_time), resource_name=resource_name)

    @property
    def position(self) -> tuple[str, str]:
        return (self.event_time, self.resource_name)


@dataclass(frozen=True)
class IngestReport:
    inserted: int
    duplicates: int
    recovered_by_lookback: int
    cursor: Cursor | None


def get_cursor(*, conn: sqlite3.Connection, space: str) -> Cursor | None:
    row = conn.execute(
        "SELECT last_event_time, last_resource_name FROM cursors WHERE space = ?",
        (space,),
    ).fetchone()
    if row is None:
        return None
    return Cursor(event_time=row[0], resource_name=row[1])


def count_recovered_by_lookback(
    *,
    conn: sqlite3.Connection,
    since: datetime | None = None,
) -> dict[str, int]:
    """Events per space that only the look-back re-read found (ADR-0035 D6)."""
    floor = "" if since is None else to_db_time(moment=since)
    rows = conn.execute(
        """
        SELECT space, COUNT(*) FROM events
         WHERE via_lookback = 1 AND received_at >= ?
         GROUP BY space ORDER BY space
        """,
        (floor,),
    ).fetchall()
    return {row[0]: int(row[1]) for row in rows}


def _insert(
    *,
    conn: sqlite3.Connection,
    event: ChatEvent,
    behind_cursor: bool,
    received_at: str,
) -> bool:
    row = conn.execute(
        """
        INSERT INTO events (
            event_key, type, space, resource_name, sender, event_time,
            received_at, source, via_lookback, payload
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (event_key) DO NOTHING
        RETURNING id
        """,
        (
            event.event_key,
            event.type,
            event.space,
            event.resource_name,
            event.sender,
            event.db_time,
            received_at,
            event.source.value,
            int(behind_cursor),
            event.payload_json,
        ),
    ).fetchone()
    return row is not None


def _store_cursor(
    *,
    conn: sqlite3.Connection,
    space: str,
    cursor: Cursor,
    updated_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO cursors (space, last_event_time, last_resource_name, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (space) DO UPDATE SET
            last_event_time = excluded.last_event_time,
            last_resource_name = excluded.last_resource_name,
            updated_at = excluded.updated_at
        """,
        (space, cursor.event_time, cursor.resource_name, updated_at),
    )


def ingest_events(
    *,
    conn: sqlite3.Connection,
    space: str,
    events: Sequence[ChatEvent],
    now: datetime,
    read_up_to: Cursor | None = None,
) -> Result[IngestReport]:
    """Store each event once and advance the space cursor atomically.

    ``read_up_to`` is the position a sequential reader (poll or backfill)
    has listed through; a push source passes nothing. The cursor only
    ever moves forward, and only in the transaction that commits the
    events (ADR-0035 D5). When a sequential reader inserts an event at
    or behind the stored cursor, only the look-back re-read could have
    found it, so it is flagged ``via_lookback`` to make indexing lag
    measurable (D6). A late push delivery is not look-back recovery and
    is never flagged.
    """
    foreign = sorted({event.space for event in events if event.space != space})
    if foreign:
        return err(f"Events from other spaces passed to the {space} ingest", spaces=foreign)
    stamp = to_db_time(moment=now)
    inserted = duplicates = recovered = 0
    try:
        with write_transaction(conn=conn) as tx:
            stored = get_cursor(conn=tx, space=space)
            sequential = read_up_to is not None
            for event in sorted(events, key=lambda candidate: candidate.position):
                behind = sequential and stored is not None and event.position <= stored.position
                if not _insert(conn=tx, event=event, behind_cursor=behind, received_at=stamp):
                    duplicates += 1
                    continue
                inserted += 1
                recovered += int(behind)
            cursor = stored
            if read_up_to is not None and (
                stored is None or read_up_to.position > stored.position
            ):
                _store_cursor(conn=tx, space=space, cursor=read_up_to, updated_at=stamp)
                cursor = read_up_to
    except sqlite3.Error as exc:
        log.error("Chat bus ingest failed for %s: %s", space, exc)
        return err(f"Chat bus ingest failed for {space}: {exc}", space=space)
    if recovered:
        log.info("Look-back window recovered %d event(s) in %s", recovered, space)
    return ok(
        IngestReport(
            inserted=inserted,
            duplicates=duplicates,
            recovered_by_lookback=recovered,
            cursor=cursor,
        )
    )
