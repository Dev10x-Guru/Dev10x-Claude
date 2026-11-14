from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from dev10x.comm.chatbus.events import to_db_time
from dev10x.comm.chatbus.store import write_transaction
from dev10x.domain.common.result import Result, err, ok

log = logging.getLogger(__name__)


class WorkKind(StrEnum):
    REPLY = "reply"
    PRIVILEGED = "privileged"


class WorkStatus(StrEnum):
    QUEUED = "queued"
    AWAITING_APPROVAL = "awaiting_approval"
    CLAIMED = "claimed"
    DONE = "done"
    REJECTED = "rejected"


ENQUEUE_STATUSES = frozenset({WorkStatus.QUEUED, WorkStatus.AWAITING_APPROVAL})

_COLUMNS = "id, event_id, kind, status, claimed_by, claimed_until, attempts, result"


@dataclass(frozen=True)
class WorkItem:
    id: int
    event_id: int
    kind: WorkKind
    status: WorkStatus
    claimed_by: str | None
    claimed_until: str | None
    attempts: int
    result: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> WorkItem:
        return cls(
            id=row["id"],
            event_id=row["event_id"],
            kind=WorkKind(row["kind"]),
            status=WorkStatus(row["status"]),
            claimed_by=row["claimed_by"],
            claimed_until=row["claimed_until"],
            attempts=row["attempts"],
            result=row["result"],
        )


def enqueue(
    *,
    conn: sqlite3.Connection,
    event_id: int,
    kind: WorkKind,
    now: datetime,
    status: WorkStatus = WorkStatus.QUEUED,
) -> Result[WorkItem]:
    """Queue one work item per (event, kind); a repeat returns the existing item."""
    if status not in ENQUEUE_STATUSES:
        return err(f"A new work item cannot start as {status.value}", status=status.value)
    stamp = to_db_time(moment=now)
    try:
        with write_transaction(conn=conn) as tx:
            tx.execute(
                """
                INSERT INTO work_items (event_id, kind, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (event_id, kind) DO NOTHING
                """,
                (event_id, kind.value, status.value, stamp, stamp),
            )
            row = tx.execute(
                f"SELECT {_COLUMNS} FROM work_items WHERE event_id = ? AND kind = ?",
                (event_id, kind.value),
            ).fetchone()
    except sqlite3.Error as exc:
        log.error("Cannot queue work for event %s: %s", event_id, exc)
        return err(f"Cannot queue work for event {event_id}: {exc}", event_id=event_id)
    return ok(WorkItem.from_row(row))


def claim(
    *,
    conn: sqlite3.Connection,
    claimer: str,
    lease: timedelta,
    now: datetime,
    kind: WorkKind | None = None,
) -> Result[WorkItem | None]:
    """Claim the oldest claimable item, or return None when the queue is empty.

    A lapsed lease counts as claimable, so an item held by a session
    that died with a restart comes back on its own (ADR-0035 D4).
    ``kind`` limits the claim to one kind of work; None takes any.
    """
    if not claimer.strip():
        return err("A claim needs a non-empty claimer name")
    if lease <= timedelta(0):
        return err("A claim needs a positive lease", lease_seconds=lease.total_seconds())
    stamp = to_db_time(moment=now)
    wanted_kind = None if kind is None else kind.value
    try:
        with write_transaction(conn=conn) as tx:
            row = tx.execute(
                f"""
                UPDATE work_items
                   SET status = 'claimed', claimed_by = ?, claimed_until = ?,
                       attempts = attempts + 1, updated_at = ?
                 WHERE id = (
                       SELECT id FROM work_items
                        WHERE (status = 'queued'
                               OR (status = 'claimed' AND claimed_until <= ?))
                          AND (? IS NULL OR kind = ?)
                        ORDER BY id
                        LIMIT 1)
                RETURNING {_COLUMNS}
                """,
                (
                    claimer,
                    to_db_time(moment=now + lease),
                    stamp,
                    stamp,
                    wanted_kind,
                    wanted_kind,
                ),
            ).fetchone()
    except sqlite3.Error as exc:
        log.error("Chat bus claim failed for %s: %s", claimer, exc)
        return err(f"Chat bus claim failed: {exc}", claimer=claimer)
    return ok(None if row is None else WorkItem.from_row(row))


def _finish_claim(
    *,
    conn: sqlite3.Connection,
    item_id: int,
    claimer: str,
    assignments: str,
    parameters: tuple[object, ...],
    action: str,
) -> Result[WorkItem]:
    try:
        with write_transaction(conn=conn) as tx:
            row = tx.execute(
                f"""
                UPDATE work_items SET {assignments}
                 WHERE id = ? AND status = 'claimed' AND claimed_by = ?
                RETURNING {_COLUMNS}
                """,
                (*parameters, item_id, claimer),
            ).fetchone()
    except sqlite3.Error as exc:
        log.error("Chat bus %s failed for item %s: %s", action, item_id, exc)
        return err(f"Chat bus {action} failed: {exc}", item_id=item_id)
    if row is None:
        return err(
            f"Cannot {action} work item {item_id}: it is not claimed by {claimer}",
            item_id=item_id,
            claimer=claimer,
        )
    return ok(WorkItem.from_row(row))


def ack(
    *,
    conn: sqlite3.Connection,
    item_id: int,
    claimer: str,
    now: datetime,
    result: str = "",
) -> Result[WorkItem]:
    """Mark a claimed item done; the row stays so Overwatch can show history."""
    return _finish_claim(
        conn=conn,
        item_id=item_id,
        claimer=claimer,
        assignments="status = 'done', claimed_until = NULL, result = ?, updated_at = ?",
        parameters=(result, to_db_time(moment=now)),
        action="ack",
    )


def release(
    *,
    conn: sqlite3.Connection,
    item_id: int,
    claimer: str,
    now: datetime,
) -> Result[WorkItem]:
    """Hand a claimed item back to the queue before its lease runs out."""
    return _finish_claim(
        conn=conn,
        item_id=item_id,
        claimer=claimer,
        assignments=("status = 'queued', claimed_by = NULL, claimed_until = NULL, updated_at = ?"),
        parameters=(to_db_time(moment=now),),
        action="release",
    )


def hand_over(
    *,
    conn: sqlite3.Connection,
    item_id: int,
    claimer: str,
    to: str,
    lease: timedelta,
    now: datetime,
    note: str,
) -> Result[WorkItem]:
    """Pass a live claim to the session that will answer the item (ADR-0035 D10)."""
    if not to.strip():
        return err("A hand-over needs a non-empty session name", item_id=item_id)
    if lease <= timedelta(0):
        return err("A hand-over needs a positive lease", lease_seconds=lease.total_seconds())
    return _finish_claim(
        conn=conn,
        item_id=item_id,
        claimer=claimer,
        assignments="claimed_by = ?, claimed_until = ?, result = ?, updated_at = ?",
        parameters=(to, to_db_time(moment=now + lease), note, to_db_time(moment=now)),
        action="hand over",
    )


def defer(
    *,
    conn: sqlite3.Connection,
    item_id: int,
    claimer: str,
    now: datetime,
    reason: str | None,
    refund_attempt: bool,
) -> Result[WorkItem]:
    """Put a claimed item back in the queue and record why.

    ``refund_attempt`` undoes the claim's attempt count when nothing was
    tried, so waiting for herdr never counts toward the poison limit.
    A None ``reason`` keeps the reason already on record.
    """
    return _finish_claim(
        conn=conn,
        item_id=item_id,
        claimer=claimer,
        assignments=(
            "status = 'queued', claimed_by = NULL, claimed_until = NULL, "
            "attempts = MAX(attempts - ?, 0), result = COALESCE(?, result), updated_at = ?"
        ),
        parameters=(int(refund_attempt), reason, to_db_time(moment=now)),
        action="defer",
    )


def reject(
    *,
    conn: sqlite3.Connection,
    item_id: int,
    claimer: str,
    now: datetime,
    reason: str,
) -> Result[WorkItem]:
    """Stop working a claimed item for good; the reason stays visible in ``result``."""
    return _finish_claim(
        conn=conn,
        item_id=item_id,
        claimer=claimer,
        assignments="status = 'rejected', claimed_until = NULL, result = ?, updated_at = ?",
        parameters=(reason, to_db_time(moment=now)),
        action="reject",
    )


def get_item(*, conn: sqlite3.Connection, item_id: int) -> Result[WorkItem]:
    """Read one item back, e.g. to confirm a write landed (GH-1424 pattern)."""
    try:
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM work_items WHERE id = ?", (item_id,)
        ).fetchone()
    except sqlite3.Error as exc:
        log.error("Cannot read Chat bus work item %s: %s", item_id, exc)
        return err(f"Cannot read Chat bus work item {item_id}: {exc}", item_id=item_id)
    if row is None:
        return err(f"No Chat bus work item {item_id}", item_id=item_id)
    return ok(WorkItem.from_row(row))
