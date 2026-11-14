"""Poll source: read watched spaces, DMs and threads into the bus (ADR-0035 D1, D6).

Each tick lists the newest page of every watched conversation and hands
it to ``ingest_events`` as a sequential reader. Messages up to
``look_back`` behind the stored cursor are re-offered on every tick, so
one indexed late is still stored, flagged ``via_lookback``; the
``event_key`` UNIQUE constraint makes the re-read harmless. The armed
``gchat_watch`` watches are one input to this source, so the watcher's
conversations land in the bus without a second poller.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol

from dev10x.comm.chatbus.events import (
    MESSAGE_CREATED,
    ChatEvent,
    EventSource,
    from_db_time,
    to_db_time,
)
from dev10x.comm.chatbus.ingest import Cursor, IngestReport, get_cursor, ingest_events
from dev10x.comm.skills.notifications.gchat_watch import ChatMessage, Watch, parse_message
from dev10x.domain.common.result import ErrorResult, Result, err, ok

log = logging.getLogger(__name__)

DIRECT_MESSAGE = "DIRECT_MESSAGE"


@dataclass(frozen=True)
class PollLimits:
    # ADR-0035 D8 defaults.
    tick: timedelta = timedelta(seconds=60)
    max_spaces: int = 20
    page_size: int = 100
    look_back: timedelta = timedelta(minutes=5)


@dataclass(frozen=True)
class WatchedSpace:
    """One space to poll; no threads means the whole space is watched."""

    space: str
    threads: tuple[str, ...] = ()
    direct_message: bool = False


class RawMessageReader(Protocol):
    def __call__(
        self,
        *,
        space: str,
        thread: str | None,
        max_results: int,
    ) -> Result[list[Mapping[str, Any]]]: ...


@dataclass(frozen=True)
class SpacePoll:
    report: IngestReport
    read: int
    malformed: int
    truncated: bool


@dataclass(frozen=True)
class PollTick:
    spaces: Mapping[str, SpacePoll] = field(default_factory=dict)
    failures: Mapping[str, str] = field(default_factory=dict)
    skipped: tuple[str, ...] = ()

    @property
    def recovered_by_lookback(self) -> int:
        return sum(poll.report.recovered_by_lookback for poll in self.spaces.values())


def watched_from_watches(*, watches: Iterable[Watch], now: datetime) -> list[WatchedSpace]:
    """Fold the armed gchat_watch watches into poll targets.

    A whole-space watch covers every thread in it, so thread watches in
    that space are dropped instead of read twice.
    """
    whole: set[str] = set()
    threads: dict[str, list[str]] = {}
    for watch in watches:
        if watch.expires_at <= now:
            continue
        if watch.thread is None:
            whole.add(watch.space)
            continue
        threads.setdefault(watch.space, []).append(watch.thread)
    targets = [WatchedSpace(space=space) for space in whole]
    targets += [
        WatchedSpace(space=space, threads=tuple(sorted(set(names))))
        for space, names in threads.items()
        if space not in whole
    ]
    return sorted(targets, key=lambda target: target.space)


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def message_resource(
    *,
    raw: Mapping[str, Any],
    message: ChatMessage,
    space: str,
    direct_message: bool,
) -> dict[str, Any]:
    """The listed message rewritten into the Pub/Sub ``message`` resource (D5)."""
    resource = {key: value for key, value in raw.items() if key != "resource"}
    resource["name"] = message.name
    sender = _mapping(raw.get("sender"))
    sender["name"] = message.sender
    resource["sender"] = sender
    if message.thread:
        resource["thread"] = {**_mapping(raw.get("thread")), "name": message.thread}
    space_resource = _mapping(raw.get("space"))
    space_resource["name"] = space
    if direct_message:
        space_resource.setdefault("spaceType", DIRECT_MESSAGE)
    resource["space"] = space_resource
    return resource


def message_event(
    *,
    raw: Mapping[str, Any],
    space: str,
    direct_message: bool,
    source: EventSource = EventSource.POLL,
) -> ChatEvent | None:
    message = parse_message(raw=raw)
    if message is None:
        return None
    try:
        return ChatEvent(
            type=MESSAGE_CREATED,
            resource_name=message.name,
            space=space,
            sender=message.sender,
            event_time=message.created,
            payload={
                "message": message_resource(
                    raw=raw, message=message, space=space, direct_message=direct_message
                )
            },
            source=source,
        )
    except ValueError as exc:
        log.warning("Skipping a Chat message from %s that the bus cannot hold: %s", space, exc)
        return None


def _read(
    *,
    reader: RawMessageReader,
    target: WatchedSpace,
    page_size: int,
) -> Result[list[list[Mapping[str, Any]]]]:
    pages: list[list[Mapping[str, Any]]] = []
    for thread in target.threads or (None,):
        listed = reader(space=target.space, thread=thread, max_results=page_size)
        if isinstance(listed, ErrorResult):
            return listed
        pages.append(listed.value)
    return ok(pages)


def _floor(*, stored: Cursor | None, look_back: timedelta) -> str | None:
    if stored is None:
        return None
    return to_db_time(moment=from_db_time(value=stored.event_time) - look_back)


def _is_truncated(
    *,
    pages: Sequence[Sequence[Mapping[str, Any]]],
    events: Sequence[ChatEvent],
    floor: str | None,
    page_size: int,
) -> bool:
    # A full page whose oldest message is still inside the window may
    # hide older unread messages; backfill (GH-1841) recovers those.
    if floor is None or not any(len(page) >= page_size for page in pages):
        return False
    return not events or min(event.db_time for event in events) > floor


def poll_space(
    *,
    conn: sqlite3.Connection,
    reader: RawMessageReader,
    target: WatchedSpace,
    now: datetime,
    limits: PollLimits = PollLimits(),
) -> Result[SpacePoll]:
    read = _read(reader=reader, target=target, page_size=limits.page_size)
    if isinstance(read, ErrorResult):
        return read
    pages = read.value
    listed = [item for page in pages for item in page]
    parsed = [
        message_event(raw=item, space=target.space, direct_message=target.direct_message)
        for item in listed
    ]
    events = [event for event in parsed if event is not None]
    floor = _floor(stored=get_cursor(conn=conn, space=target.space), look_back=limits.look_back)
    window = [event for event in events if floor is None or event.db_time >= floor]
    truncated = _is_truncated(pages=pages, events=events, floor=floor, page_size=limits.page_size)
    if truncated:
        log.warning("Chat poll of %s filled a page; older messages may be unread", target.space)
    newest = max(window, key=lambda event: event.position, default=None)
    read_up_to = (
        None
        if newest is None
        else Cursor(event_time=newest.db_time, resource_name=newest.resource_name)
    )
    ingested = ingest_events(
        conn=conn, space=target.space, events=window, now=now, read_up_to=read_up_to
    )
    if isinstance(ingested, ErrorResult):
        return ingested
    return ok(
        SpacePoll(
            report=ingested.value,
            read=len(listed),
            malformed=len(listed) - len(events),
            truncated=truncated,
        )
    )


def poll_tick(
    *,
    conn: sqlite3.Connection,
    reader: RawMessageReader,
    targets: Sequence[WatchedSpace],
    now: datetime,
    limits: PollLimits = PollLimits(),
) -> Result[PollTick]:
    """Poll every target once; one failing space does not stop the others."""
    spaces = sorted({target.space for target in targets})
    if len(spaces) != len(targets):
        return err("Each watched space must appear once in a poll tick", spaces=spaces)
    ordered = sorted(targets, key=lambda target: target.space)
    polled, skipped = ordered[: limits.max_spaces], ordered[limits.max_spaces :]
    if skipped:
        log.warning(
            "Chat poll watches %d spaces; only the first %d are read",
            len(ordered),
            limits.max_spaces,
        )
    results: dict[str, SpacePoll] = {}
    failures: dict[str, str] = {}
    for target in polled:
        outcome = poll_space(conn=conn, reader=reader, target=target, now=now, limits=limits)
        if isinstance(outcome, ErrorResult):
            log.warning("Chat poll of %s failed: %s", target.space, outcome.error)
            failures[target.space] = outcome.error
            continue
        results[target.space] = outcome.value
    return ok(
        PollTick(
            spaces=results,
            failures=failures,
            skipped=tuple(target.space for target in skipped),
        )
    )
