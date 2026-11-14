"""The queue operations behind the ``chat_queue_*`` MCP tools (GH-1842).

Each call opens the user's store, does one short operation and closes
it. Writes are re-read before they are reported, so a caller sees the
status the row actually holds rather than an echo of its own request
(the GH-1424 pattern).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from dev10x.comm.chatbus import queue, worklist
from dev10x.comm.chatbus.queue import WorkKind, WorkStatus
from dev10x.comm.chatbus.store import open_store
from dev10x.comm.chatbus.worklist import UNTRUSTED_NOTICE, ChatPoster
from dev10x.domain.common.result import ErrorResult, Result, err, ok
from dev10x.domain.dev10x_paths import Dev10xConfigDir


def _with_store[T](
    *,
    path: Path | None,
    operation: Callable[[sqlite3.Connection], Result[T]],
) -> Result[T]:
    opened = open_store(path=path or Dev10xConfigDir.chat_bus_db())
    if isinstance(opened, ErrorResult):
        return opened
    try:
        return operation(opened.value)
    finally:
        opened.value.close()


def _parse_statuses(*, status: Sequence[str] | None) -> Result[frozenset[WorkStatus]]:
    if status is None:
        return ok(worklist.OPEN_STATUSES)
    known = {member.value for member in WorkStatus}
    unknown = sorted(set(status) - known)
    if unknown:
        return err(
            f"Unknown work item status {', '.join(unknown)}; expected one of "
            f"{', '.join(sorted(known))}",
            unknown=unknown,
        )
    return ok(frozenset(WorkStatus(value) for value in status))


def list_items(
    *,
    status: Sequence[str] | None,
    limit: int,
    path: Path | None = None,
) -> Result[dict[str, Any]]:
    statuses = _parse_statuses(status=status)
    if isinstance(statuses, ErrorResult):
        return statuses

    def operation(conn: sqlite3.Connection) -> Result[dict[str, Any]]:
        views = worklist.list_work(conn=conn, statuses=statuses.value, limit=limit)
        if isinstance(views, ErrorResult):
            return views
        items = [view.to_dict() for view in views.value]
        return ok({"items": items, "count": len(items), "notice": UNTRUSTED_NOTICE})

    return _with_store(path=path, operation=operation)


def claim_item(
    *,
    claimer: str,
    kind: str,
    lease: timedelta,
    now: datetime,
    path: Path | None = None,
) -> Result[dict[str, Any]]:
    if kind not in {member.value for member in WorkKind}:
        return err(f"Unknown work kind {kind!r}; expected reply or privileged", kind=kind)

    def operation(conn: sqlite3.Connection) -> Result[dict[str, Any]]:
        claimed = queue.claim(
            conn=conn, claimer=claimer, lease=lease, now=now, kind=WorkKind(kind)
        )
        if isinstance(claimed, ErrorResult):
            return claimed
        if claimed.value is None:
            return ok({"claimed": False})
        observed = worklist.get_view(conn=conn, item_id=claimed.value.id)
        if isinstance(observed, ErrorResult):
            return observed
        item = observed.value.item
        return ok(
            {
                "claimed": True,
                "item": observed.value.to_dict(),
                "observed_status": item.status.value,
                "claim_verified": item.status is WorkStatus.CLAIMED and item.claimed_by == claimer,
                "notice": UNTRUSTED_NOTICE,
            }
        )

    return _with_store(path=path, operation=operation)


def reply_to_item(
    *,
    item_id: int,
    claimer: str,
    text: str,
    now: datetime,
    poster: ChatPoster,
    path: Path | None = None,
) -> Result[dict[str, Any]]:
    def operation(conn: sqlite3.Connection) -> Result[dict[str, Any]]:
        posted = worklist.reply(
            conn=conn, item_id=item_id, claimer=claimer, text=text, now=now, poster=poster
        )
        if isinstance(posted, ErrorResult):
            return posted
        reply = posted.value
        return ok({"item_id": reply.item_id, "message": reply.message, "thread": reply.thread})

    return _with_store(path=path, operation=operation)


def ack_item(
    *,
    item_id: int,
    claimer: str,
    result: str,
    now: datetime,
    path: Path | None = None,
) -> Result[dict[str, Any]]:
    def operation(conn: sqlite3.Connection) -> Result[dict[str, Any]]:
        acked = queue.ack(conn=conn, item_id=item_id, claimer=claimer, now=now, result=result)
        if isinstance(acked, ErrorResult):
            return acked
        observed = queue.get_item(conn=conn, item_id=item_id)
        if isinstance(observed, ErrorResult):
            return observed
        item = observed.value
        return ok(
            {
                "item_id": item.id,
                "observed_status": item.status.value,
                "result": item.result,
                "ack_verified": item.status is WorkStatus.DONE and item.result == result,
            }
        )

    return _with_store(path=path, operation=operation)
