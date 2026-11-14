"""What ``dev10x chatbus status`` reports: subscription, cursors, queue, gaps (ADR-0035 D9).

Read-only. A store that does not exist yet reads as empty, and is not
created by looking at it.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from dev10x.comm.chatbus.backfill import Gap, open_gaps
from dev10x.comm.chatbus.events import from_db_time, to_db_time
from dev10x.comm.chatbus.queue import WorkStatus
from dev10x.comm.chatbus.store import open_store
from dev10x.domain.common.result import ErrorResult, Result, err, ok

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SubscriptionRow:
    target: str
    name: str
    expire_time: datetime
    renewed_at: datetime


@dataclass(frozen=True)
class CursorRow:
    space: str
    last_event_time: datetime
    updated_at: datetime


@dataclass(frozen=True)
class BusStatus:
    store: Path
    exists: bool
    subscriptions: tuple[SubscriptionRow, ...] = ()
    cursors: tuple[CursorRow, ...] = ()
    queue: dict[str, int] = field(default_factory=dict)
    expired_leases: int = 0
    gaps: tuple[Gap, ...] = ()

    def to_dict(self, *, now: datetime) -> dict[str, Any]:
        return {
            "store": str(self.store),
            "exists": self.exists,
            "subscriptions": [
                {
                    "target": row.target,
                    "name": row.name,
                    "expire_time": to_db_time(moment=row.expire_time),
                    "expires_in_seconds": int((row.expire_time - now).total_seconds()),
                    "renewed_at": to_db_time(moment=row.renewed_at),
                }
                for row in self.subscriptions
            ],
            "cursors": [
                {
                    "space": row.space,
                    "last_event_time": to_db_time(moment=row.last_event_time),
                    "event_age_seconds": int((now - row.last_event_time).total_seconds()),
                    "updated_age_seconds": int((now - row.updated_at).total_seconds()),
                }
                for row in self.cursors
            ],
            "queue": dict(self.queue),
            "expired_leases": self.expired_leases,
            "gaps": [
                {
                    "id": gap.id,
                    "space": gap.space,
                    "from": to_db_time(moment=gap.from_time),
                    "to": to_db_time(moment=gap.to_time),
                    "reason": gap.reason,
                }
                for gap in self.gaps
            ],
        }


def empty_queue() -> dict[str, int]:
    return {status.value: 0 for status in WorkStatus}


def read_status(*, conn: sqlite3.Connection, path: Path, now: datetime) -> Result[BusStatus]:
    try:
        subscriptions = conn.execute(
            "SELECT target, name, expire_time, renewed_at FROM subscriptions ORDER BY target"
        ).fetchall()
        cursors = conn.execute(
            "SELECT space, last_event_time, updated_at FROM cursors ORDER BY space"
        ).fetchall()
        counts = conn.execute("SELECT status, COUNT(*) FROM work_items GROUP BY status").fetchall()
        expired = conn.execute(
            "SELECT COUNT(*) FROM work_items WHERE status = 'claimed' AND claimed_until <= ?",
            (to_db_time(moment=now),),
        ).fetchone()[0]
        gaps = open_gaps(conn=conn)
    except sqlite3.Error as exc:
        log.error("Cannot read the Chat bus status from %s: %s", path, exc)
        return err(f"Cannot read the Chat bus status from {path}: {exc}", path=str(path))
    queue = empty_queue()
    queue.update({row[0]: int(row[1]) for row in counts})
    return ok(
        BusStatus(
            store=path,
            exists=True,
            subscriptions=tuple(
                SubscriptionRow(
                    target=row[0],
                    name=row[1],
                    expire_time=from_db_time(value=row[2]),
                    renewed_at=from_db_time(value=row[3]),
                )
                for row in subscriptions
            ),
            cursors=tuple(
                CursorRow(
                    space=row[0],
                    last_event_time=from_db_time(value=row[1]),
                    updated_at=from_db_time(value=row[2]),
                )
                for row in cursors
            ),
            queue=queue,
            expired_leases=int(expired),
            gaps=tuple(gaps),
        )
    )


def get_status(*, path: Path, now: datetime) -> Result[BusStatus]:
    if not path.exists():
        return ok(BusStatus(store=path, exists=False, queue=empty_queue()))
    opened = open_store(path=path)
    if isinstance(opened, ErrorResult):
        return opened
    try:
        return read_status(conn=opened.value, path=path, now=now)
    finally:
        opened.value.close()


def _ago(*, delta: timedelta) -> str:
    if delta < timedelta(0):
        return f"{_span(delta=-delta)} ahead"
    return f"{_span(delta=delta)} ago"


def _span(*, delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    if seconds < 120:
        return f"{seconds}s"
    if seconds < 2 * 3600:
        return f"{seconds // 60}m"
    if seconds < 2 * 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def render_status(*, status: BusStatus, now: datetime, service: str) -> str:
    lines = [f"Service: {service}", f"Store: {status.store}"]
    if not status.exists:
        lines.append("  not created yet; `dev10x chatbus run` creates it")
    lines.append("Subscription:")
    if not status.subscriptions:
        lines.append("  none recorded")
    for sub in status.subscriptions:
        left = sub.expire_time - now
        state = f"expires in {_span(delta=left)}" if left > timedelta(0) else "EXPIRED"
        lines.append(f"  {sub.name} ({state}, renewed {_ago(delta=now - sub.renewed_at)})")
    lines.append("Cursors:")
    if not status.cursors:
        lines.append("  none yet")
    for cursor in status.cursors:
        lines.append(
            f"  {cursor.space}: last event {_ago(delta=now - cursor.last_event_time)}, "
            f"advanced {_ago(delta=now - cursor.updated_at)}"
        )
    depth = ", ".join(f"{name} {count}" for name, count in status.queue.items())
    lines.append(f"Queue: {depth}; expired leases {status.expired_leases}")
    lines.append(f"Open gaps: {len(status.gaps)}")
    for gap in status.gaps:
        lines.append(
            f"  {gap.space}: {to_db_time(moment=gap.from_time)} .. "
            f"{to_db_time(moment=gap.to_time)} ({gap.reason})"
        )
    return "\n".join(lines)
