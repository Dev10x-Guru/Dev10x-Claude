"""What the Overwatch page shows of the Chat bus (ADR-0035 D3, D7, D9).

Read-only. The store is opened in SQLite's read-only mode, so looking at
it never creates, migrates or writes it, and the allowlist is read from
the config without logging or caching it. Every ``untrusted_text`` and
``reason`` field carries what a Chat user typed: the page shows it as
text and never as markup or an instruction.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from dev10x.comm.chatbus.authz import Allowlist, build_allowlist
from dev10x.comm.chatbus.queue import WorkStatus
from dev10x.comm.chatbus.schema import SCHEMA_VERSION
from dev10x.comm.chatbus.status import BusStatus, empty_queue, read_status
from dev10x.comm.chatbus.store import BUSY_TIMEOUT_SECONDS
from dev10x.comm.chatbus.worklist import WorkView, event_text, event_thread, list_work
from dev10x.comm.skills.notifications.gchat_users import load_chat_users
from dev10x.core.domain.common.result import ErrorResult, Result, err, ok

log = logging.getLogger(__name__)

DEFAULT_LIMIT = 50
TEXT_LIMIT = 500
ELLIPSIS = "…"

_EVENT_QUERY = """
    SELECT id, type, space, resource_name, sender, event_time, received_at, source, payload
      FROM events
     ORDER BY id DESC
     LIMIT ?
"""
_COMMAND_QUERY = """
    SELECT id, event_id, actor, verb, authorized, outcome, reason, work_item_id, created_at
      FROM commands
     ORDER BY id DESC
     LIMIT ?
"""


def clip(*, text: str, limit: int = TEXT_LIMIT) -> str:
    return text if len(text) <= limit else text[: limit - len(ELLIPSIS)] + ELLIPSIS


@dataclass(frozen=True)
class BoardEvent:
    id: int
    type: str
    space: str
    sender: str
    source: str
    event_time: str
    received_at: str
    thread: str | None
    untrusted_text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "space": self.space,
            "sender": self.sender,
            "source": self.source,
            "event_time": self.event_time,
            "received_at": self.received_at,
            "thread": self.thread,
            "untrusted_text": self.untrusted_text,
        }


@dataclass(frozen=True)
class BoardCommand:
    id: int
    event_id: int
    actor: str
    verb: str
    authorized: bool
    outcome: str | None
    reason: str
    work_item_id: int | None
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "event_id": self.event_id,
            "actor": self.actor,
            "verb": self.verb,
            "authorized": self.authorized,
            "outcome": self.outcome,
            "reason": self.reason,
            "work_item_id": self.work_item_id,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class AllowlistView:
    """The allowlist as the config reads now; the daemon applies it on start or reload."""

    config: Path
    owner: str | None = None
    trusted: tuple[str, ...] = ()
    logins: dict[str, str] = field(default_factory=dict)
    error: str | None = None

    @classmethod
    def from_allowlist(cls, *, config: Path, allowlist: Allowlist) -> AllowlistView:
        members = {allowlist.owner, *allowlist.trusted}
        return cls(
            config=config,
            owner=allowlist.owner,
            trusted=tuple(sorted(allowlist.trusted)),
            logins={user: allowlist.logins[user] for user in members if user in allowlist.logins},
        )

    def to_dict(self) -> dict[str, Any]:
        def entry(user: str) -> dict[str, str | None]:
            return {"chat_user": user, "login": self.logins.get(user)}

        return {
            "config": str(self.config),
            "owner": None if self.owner is None else entry(self.owner),
            "trusted": [entry(user) for user in self.trusted],
            "error": self.error,
        }


@dataclass(frozen=True)
class ChatBoard:
    status: BusStatus
    allowlist: AllowlistView
    events: tuple[BoardEvent, ...] = ()
    commands: tuple[BoardCommand, ...] = ()
    work: tuple[WorkView, ...] = ()

    def to_dict(self, *, now: datetime) -> dict[str, Any]:
        def work_item(view: WorkView) -> dict[str, Any]:
            item = view.to_dict()
            return {**item, "untrusted_text": clip(text=item["untrusted_text"])}

        return {
            **self.status.to_dict(now=now),
            "allowlist": self.allowlist.to_dict(),
            "events": [event.to_dict() for event in self.events],
            "commands": [command.to_dict() for command in self.commands],
            "work_items": [work_item(view) for view in self.work],
        }


def open_read_only(*, path: Path) -> Result[sqlite3.Connection]:
    """Open an existing store without the right to change it, and check its schema."""
    try:
        conn = sqlite3.connect(
            f"{path.resolve().as_uri()}?mode=ro",
            uri=True,
            timeout=BUSY_TIMEOUT_SECONDS,
            isolation_level=None,
        )
    except sqlite3.Error as exc:
        log.error("Cannot open the Chat bus store at %s read-only: %s", path, exc)
        return err(f"Cannot open the Chat bus store at {path}: {exc}", path=str(path))
    conn.row_factory = sqlite3.Row
    try:
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    except sqlite3.Error as exc:
        conn.close()
        log.error("Cannot read the Chat bus store at %s: %s", path, exc)
        return err(f"Cannot read the Chat bus store at {path}: {exc}", path=str(path))
    if version != SCHEMA_VERSION:
        conn.close()
        return err(
            f"The Chat bus store at {path} has schema version {version}, this dev10x reads "
            f"{SCHEMA_VERSION}; start `dev10x chatbus run` with the same dev10x to migrate it.",
            path=str(path),
            found=version,
            supported=SCHEMA_VERSION,
        )
    return ok(conn)


def read_allowlist(*, config: Path) -> AllowlistView:
    users = load_chat_users(path=config)
    if isinstance(users, ErrorResult):
        return AllowlistView(config=config, error=users.error)
    allowlist = build_allowlist(users=users.value)
    if isinstance(allowlist, ErrorResult):
        return AllowlistView(config=config, error=allowlist.error)
    return AllowlistView.from_allowlist(config=config, allowlist=allowlist.value)


def _events(*, conn: sqlite3.Connection, limit: int) -> tuple[BoardEvent, ...]:
    return tuple(
        BoardEvent(
            id=row["id"],
            type=row["type"],
            space=row["space"],
            sender=row["sender"],
            source=row["source"],
            event_time=row["event_time"],
            received_at=row["received_at"],
            thread=event_thread(
                conn=conn,
                event_type=row["type"],
                resource_name=row["resource_name"],
                raw_payload=row["payload"],
            ),
            untrusted_text=clip(text=event_text(raw_payload=row["payload"])),
        )
        for row in conn.execute(_EVENT_QUERY, (limit,)).fetchall()
    )


def _commands(*, conn: sqlite3.Connection, limit: int) -> tuple[BoardCommand, ...]:
    return tuple(
        BoardCommand(
            id=row["id"],
            event_id=row["event_id"],
            actor=row["actor"],
            verb=row["verb"],
            authorized=bool(row["authorized"]),
            outcome=row["outcome"],
            reason=clip(text=row["reason"]),
            work_item_id=row["work_item_id"],
            created_at=row["created_at"],
        )
        for row in conn.execute(_COMMAND_QUERY, (limit,)).fetchall()
    )


def read_board(
    *,
    conn: sqlite3.Connection,
    path: Path,
    allowlist: AllowlistView,
    now: datetime,
    limit: int = DEFAULT_LIMIT,
) -> Result[ChatBoard]:
    status = read_status(conn=conn, path=path, now=now)
    if isinstance(status, ErrorResult):
        return status
    work = list_work(conn=conn, statuses=tuple(WorkStatus), limit=limit, newest_first=True)
    if isinstance(work, ErrorResult):
        return work
    try:
        events = _events(conn=conn, limit=limit)
        commands = _commands(conn=conn, limit=limit)
    except sqlite3.Error as exc:
        log.error("Cannot read the Chat bus events from %s: %s", path, exc)
        return err(f"Cannot read the Chat bus events from {path}: {exc}", path=str(path))
    return ok(
        ChatBoard(
            status=status.value,
            allowlist=allowlist,
            events=events,
            commands=commands,
            work=tuple(work.value),
        )
    )


def get_board(
    *,
    path: Path,
    config: Path,
    now: datetime,
    limit: int = DEFAULT_LIMIT,
) -> Result[ChatBoard]:
    if limit < 1:
        return err("A Chat bus board needs a positive limit", limit=limit)
    allowlist = read_allowlist(config=config)
    if not path.exists():
        missing = BusStatus(store=path, exists=False, queue=empty_queue())
        return ok(ChatBoard(status=missing, allowlist=allowlist))
    opened = open_read_only(path=path)
    if isinstance(opened, ErrorResult):
        return opened
    try:
        return read_board(conn=opened.value, path=path, allowlist=allowlist, now=now, limit=limit)
    finally:
        opened.value.close()
