"""Restart and sleep backfill: recover Chat events missed during downtime (ADR-0035 D7, D8).

A Workspace Events subscription lapses after 4 hours, and nothing is
published while it is lapsed, so Pub/Sub alone cannot cover a long
sleep. Catch-up runs at start-up and whenever a tick sees a wall-clock
gap larger than twice the tick interval. It recovers in a fixed order:

1. expired leases need no work, because ``claim`` already treats an
   expired lease as claimable;
2. the lapsed subscription is recreated before anything is read, so
   nothing falls between "backfill finished" and "pull resumed";
3. each watched space is re-read from ``cursor - look_back``.

Backfilled events carry the Pub/Sub shape, so ingest dedupes them
against late Pub/Sub deliveries through ``event_key`` and authorization
treats them like live events. Reaction deletions can only be inferred:
reactions are listed for messages whose reaction summary differs from
``reaction_snapshot``, plus a bounded set of tracked recent messages,
and the diff synthesizes ``reaction.created`` / ``reaction.deleted``.
A reaction added and removed during the downtime is in neither the
snapshot nor the listing, so it produces no event.

A run reads at most ``max_reads`` pages; the remainder continues on the
next run from the advanced cursor. A truncated run, or a cursor older
than the maximum window, records a ``gaps`` row instead of dropping the
window silently.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

from dev10x.comm.chatbus.events import (
    MESSAGE_CREATED,
    REACTION_CREATED,
    REACTION_DELETED,
    ChatEvent,
    EventSource,
    from_db_time,
    to_db_time,
)
from dev10x.comm.chatbus.ingest import Cursor, get_cursor, ingest_events
from dev10x.comm.chatbus.snapshot import (
    SnapshotReaction,
    emoji_resource,
    get_snapshot,
    parse_reaction,
    reaction_summary,
    remember_reactions,
    snapshot_summary,
)
from dev10x.comm.chatbus.sources.poll import WatchedSpace, message_event
from dev10x.comm.chatbus.sources.pubsub import (
    SubscriptionApi,
    SubscriptionSpec,
    SubscriptionStatus,
    ensure_subscription,
)
from dev10x.comm.chatbus.store import write_transaction
from dev10x.domain.common.result import ErrorResult, Result, err, ok

log = logging.getLogger(__name__)

CATCH_UP_GAP_FACTOR = 2


@dataclass(frozen=True)
class BackfillLimits:
    # ADR-0035 D8 defaults.
    tick: timedelta = timedelta(seconds=60)
    max_spaces: int = 20
    page_size: int = 100
    max_reads: int = 1000
    tracked_messages: int = 200
    max_window: timedelta = timedelta(days=7)
    look_back: timedelta = timedelta(minutes=5)


class GapReason(StrEnum):
    WINDOW_EXCEEDED = "window_exceeded"
    READ_BUDGET = "read_budget"


@dataclass(frozen=True)
class Page:
    items: list[Mapping[str, Any]]
    next_page_token: str | None = None


class ChatHistoryReader(Protocol):
    def list_messages(
        self,
        *,
        space: str,
        since: datetime,
        threads: tuple[str, ...],
        page_size: int,
        page_token: str | None,
    ) -> Result[Page]:
        """Messages created after ``since``, oldest first; no threads means the whole space."""

    def list_reactions(
        self,
        *,
        message: str,
        page_size: int,
        page_token: str | None,
    ) -> Result[Page]:
        """The reactions currently on one message."""


@dataclass(frozen=True)
class SubscriptionRecovery:
    api: SubscriptionApi
    spec: SubscriptionSpec


@dataclass(frozen=True)
class Gap:
    id: int
    space: str
    from_time: datetime
    to_time: datetime
    reason: str
    detected_at: datetime


@dataclass
class ReadBudget:
    """Chat API reads left in one backfill run, shared by every space."""

    remaining: int

    def take(self) -> bool:
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        return True


@dataclass(frozen=True)
class SpaceBackfill:
    reads: int = 0
    messages_inserted: int = 0
    reactions_created: int = 0
    reactions_deleted: int = 0
    duplicates: int = 0
    recovered_by_lookback: int = 0
    malformed: int = 0
    truncated: bool = False
    window_exceeded: bool = False


@dataclass(frozen=True)
class CatchUpReport:
    subscription: SubscriptionStatus | None = None
    subscription_error: str | None = None
    spaces: Mapping[str, SpaceBackfill] = field(default_factory=dict)
    failures: Mapping[str, str] = field(default_factory=dict)
    skipped: tuple[str, ...] = ()

    @property
    def reads(self) -> int:
        return sum(space.reads for space in self.spaces.values())

    @property
    def truncated(self) -> bool:
        return any(space.truncated for space in self.spaces.values())


def catch_up_due(*, last_tick: datetime | None, now: datetime, tick: timedelta) -> bool:
    """Start-up, or a wall-clock gap the scheduler cannot explain (a sleep or a stop)."""
    return last_tick is None or now - last_tick > tick * CATCH_UP_GAP_FACTOR


def record_gap(
    *,
    conn: sqlite3.Connection,
    space: str,
    start: datetime,
    end: datetime,
    reason: GapReason,
    now: datetime,
) -> Result[int]:
    """Record a window the bus could not recover; an open gap of the same kind is widened."""
    first, last = to_db_time(moment=start), to_db_time(moment=end)
    try:
        with write_transaction(conn=conn) as tx:
            row = tx.execute(
                """
                SELECT id, from_time, to_time FROM gaps
                 WHERE space = ? AND reason = ? AND resolved_at IS NULL
                 ORDER BY id LIMIT 1
                """,
                (space, reason.value),
            ).fetchone()
            if row is None:
                gap_id = int(
                    tx.execute(
                        """
                        INSERT INTO gaps (space, from_time, to_time, reason, detected_at)
                        VALUES (?, ?, ?, ?, ?) RETURNING id
                        """,
                        (space, first, last, reason.value, to_db_time(moment=now)),
                    ).fetchone()[0]
                )
            else:
                gap_id = int(row[0])
                tx.execute(
                    "UPDATE gaps SET from_time = ?, to_time = ? WHERE id = ?",
                    (min(row[1], first), max(row[2], last), gap_id),
                )
    except sqlite3.Error as exc:
        log.error("Cannot record a Chat bus gap for %s: %s", space, exc)
        return err(f"Cannot record a Chat bus gap for {space}: {exc}", space=space)
    log.warning("Chat bus gap in %s (%s) from %s to %s", space, reason.value, first, last)
    return ok(gap_id)


def resolve_gaps(
    *,
    conn: sqlite3.Connection,
    space: str,
    reason: GapReason,
    now: datetime,
) -> Result[int]:
    try:
        with write_transaction(conn=conn) as tx:
            resolved = tx.execute(
                """
                UPDATE gaps SET resolved_at = ?
                 WHERE space = ? AND reason = ? AND resolved_at IS NULL
                """,
                (to_db_time(moment=now), space, reason.value),
            ).rowcount
    except sqlite3.Error as exc:
        log.error("Cannot resolve Chat bus gaps for %s: %s", space, exc)
        return err(f"Cannot resolve Chat bus gaps for {space}: {exc}", space=space)
    return ok(resolved)


def open_gaps(*, conn: sqlite3.Connection) -> list[Gap]:
    rows = conn.execute(
        """
        SELECT id, space, from_time, to_time, reason, detected_at FROM gaps
         WHERE resolved_at IS NULL ORDER BY space, id
        """
    ).fetchall()
    return [
        Gap(
            id=int(row[0]),
            space=row[1],
            from_time=from_db_time(value=row[2]),
            to_time=from_db_time(value=row[3]),
            reason=row[4],
            detected_at=from_db_time(value=row[5]),
        )
        for row in rows
    ]


@dataclass
class _Tally:
    reads: int = 0
    messages_inserted: int = 0
    reactions_created: int = 0
    reactions_deleted: int = 0
    duplicates: int = 0
    recovered_by_lookback: int = 0
    malformed: int = 0
    truncated: bool = False
    window_exceeded: bool = False
    listed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)

    def report(self) -> SpaceBackfill:
        return SpaceBackfill(
            reads=self.reads,
            messages_inserted=self.messages_inserted,
            reactions_created=self.reactions_created,
            reactions_deleted=self.reactions_deleted,
            duplicates=self.duplicates,
            recovered_by_lookback=self.recovered_by_lookback,
            malformed=self.malformed,
            truncated=self.truncated,
            window_exceeded=self.window_exceeded,
        )


@dataclass
class _Run:
    conn: sqlite3.Connection
    reader: ChatHistoryReader
    target: WatchedSpace
    cursor: Cursor
    now: datetime
    limits: BackfillLimits
    budget: ReadBudget
    tally: _Tally = field(default_factory=_Tally)

    def read(self) -> bool:
        if not self.budget.take():
            self.tally.truncated = True
            return False
        self.tally.reads += 1
        return True


def _read_window(*, run: _Run) -> Result[datetime]:
    """The time to read from; a cursor beyond the maximum window records its lost part."""
    cursor_time = from_db_time(value=run.cursor.event_time)
    oldest = run.now - run.limits.max_window
    if cursor_time >= oldest:
        return ok(max(cursor_time - run.limits.look_back, oldest))
    run.tally.window_exceeded = True
    recorded = record_gap(
        conn=run.conn,
        space=run.target.space,
        start=cursor_time,
        end=oldest,
        reason=GapReason.WINDOW_EXCEEDED,
        now=run.now,
    )
    if isinstance(recorded, ErrorResult):
        return recorded
    return ok(oldest)


def _ingest_page(*, run: _Run, items: Sequence[Mapping[str, Any]]) -> Result[None]:
    space = run.target.space
    parsed = [
        message_event(
            raw=raw,
            space=space,
            direct_message=run.target.direct_message,
            source=EventSource.BACKFILL,
        )
        for raw in items
    ]
    events = [event for event in parsed if event is not None]
    run.tally.malformed += len(parsed) - len(events)
    newest = max(events, key=lambda event: event.position, default=None)
    # Pages come oldest first, so the cursor advances page by page and a
    # run cut short by the budget resumes where it stopped.
    ingested = ingest_events(
        conn=run.conn,
        space=space,
        events=events,
        now=run.now,
        read_up_to=None
        if newest is None
        else Cursor(event_time=newest.db_time, resource_name=newest.resource_name),
    )
    if isinstance(ingested, ErrorResult):
        return ingested
    run.tally.messages_inserted += ingested.value.inserted
    run.tally.duplicates += ingested.value.duplicates
    run.tally.recovered_by_lookback += ingested.value.recovered_by_lookback
    for raw, event in zip(items, parsed, strict=True):
        if event is None:
            continue
        run.tally.listed.append(event.resource_name)
        listed = reaction_summary(message=raw)
        if listed != snapshot_summary(conn=run.conn, message=event.resource_name):
            run.tally.changed.append(event.resource_name)
    return ok(None)


def _backfill_messages(*, run: _Run, since: datetime) -> Result[None]:
    token: str | None = None
    while run.read():
        listed = run.reader.list_messages(
            space=run.target.space,
            since=since,
            threads=run.target.threads,
            page_size=run.limits.page_size,
            page_token=token,
        )
        if isinstance(listed, ErrorResult):
            return listed
        ingested = _ingest_page(run=run, items=listed.value.items)
        if isinstance(ingested, ErrorResult):
            return ingested
        token = listed.value.next_page_token
        if not token:
            break
    return ok(None)


def _list_all_reactions(*, run: _Run, message: str) -> Result[list[Mapping[str, Any]] | None]:
    """Every reaction on a message, or None when the budget ran out part way.

    A partial listing would read as deletions, so it is discarded whole.
    """
    reactions: list[Mapping[str, Any]] = []
    token: str | None = None
    while run.read():
        listed = run.reader.list_reactions(
            message=message, page_size=run.limits.page_size, page_token=token
        )
        if isinstance(listed, ErrorResult):
            return listed
        reactions += listed.value.items
        token = listed.value.next_page_token
        if not token:
            return ok(reactions)
    return ok(None)


def _reaction_event(
    *,
    reaction: SnapshotReaction,
    event_type: str,
    space: str,
    now: datetime,
    raw: Mapping[str, Any] | None = None,
) -> ChatEvent:
    # The Chat API gives a reaction no creation time; the diff is when it was seen.
    resource = dict(raw or {})
    user = resource.get("user")
    resource.update(
        name=reaction.name,
        user={**(user if isinstance(user, Mapping) else {}), "name": reaction.user},
        emoji=resource.get("emoji") or emoji_resource(key=reaction.emoji),
    )
    return ChatEvent(
        type=event_type,
        resource_name=reaction.name,
        space=space,
        sender=reaction.user,
        event_time=now,
        payload={"reaction": resource},
        source=EventSource.BACKFILL,
    )


def _diff_reactions(
    *,
    run: _Run,
    message: str,
    listed: Sequence[Mapping[str, Any]],
) -> Result[None]:
    current: dict[str, tuple[SnapshotReaction, Mapping[str, Any]]] = {}
    for raw in listed:
        parsed = parse_reaction(raw=raw, message=message)
        if parsed is None:
            run.tally.malformed += 1
            continue
        current[parsed.name] = (parsed, raw)
    known = get_snapshot(conn=run.conn, message=message)
    space = run.target.space
    created = [
        _reaction_event(
            reaction=reaction, event_type=REACTION_CREATED, space=space, now=run.now, raw=raw
        )
        for name, (reaction, raw) in sorted(current.items())
        if name not in known
    ]
    deleted = [
        _reaction_event(reaction=reaction, event_type=REACTION_DELETED, space=space, now=run.now)
        for name, reaction in sorted(known.items())
        if name not in current
    ]
    events = created + deleted
    if not events:
        return ok(None)
    ingested = ingest_events(conn=run.conn, space=space, events=events, now=run.now)
    if isinstance(ingested, ErrorResult):
        return ingested
    run.tally.reactions_created += len(created)
    run.tally.reactions_deleted += len(deleted)
    run.tally.duplicates += ingested.value.duplicates
    remembered = remember_reactions(conn=run.conn, events=events, now=run.now)
    if isinstance(remembered, ErrorResult):
        return remembered
    return ok(None)


def _backfill_reactions(*, run: _Run) -> Result[None]:
    space = run.target.space
    listed_now = set(run.tally.listed)
    tracked = [
        message
        for message in _tracked_messages(
            conn=run.conn, space=space, limit=run.limits.tracked_messages
        )
        if message not in listed_now
    ]
    for message in dict.fromkeys(run.tally.changed + tracked):
        reactions = _list_all_reactions(run=run, message=message)
        if isinstance(reactions, ErrorResult):
            return reactions
        if reactions.value is None:
            break
        diffed = _diff_reactions(run=run, message=message, listed=reactions.value)
        if isinstance(diffed, ErrorResult):
            return diffed
    return ok(None)


def _tracked_messages(*, conn: sqlite3.Connection, space: str, limit: int) -> list[str]:
    rows = conn.execute(
        """
        SELECT resource_name FROM events
         WHERE space = ? AND type = ?
         ORDER BY event_time DESC, resource_name DESC
         LIMIT ?
        """,
        (space, MESSAGE_CREATED, limit),
    ).fetchall()
    return [row[0] for row in rows]


def _settle_budget_gap(*, run: _Run) -> Result[int]:
    space = run.target.space
    if not run.tally.truncated:
        return resolve_gaps(conn=run.conn, space=space, reason=GapReason.READ_BUDGET, now=run.now)
    # The cursor marks how far this run got; the gap is everything after it.
    reached = get_cursor(conn=run.conn, space=space) or run.cursor
    return record_gap(
        conn=run.conn,
        space=space,
        start=min(from_db_time(value=reached.event_time), run.now),
        end=run.now,
        reason=GapReason.READ_BUDGET,
        now=run.now,
    )


def backfill_space(
    *,
    conn: sqlite3.Connection,
    reader: ChatHistoryReader,
    target: WatchedSpace,
    now: datetime,
    limits: BackfillLimits = BackfillLimits(),
    budget: ReadBudget | None = None,
) -> Result[SpaceBackfill]:
    """Re-read one space from its cursor, then diff the reactions it may have missed.

    A space the bus has never read has no cursor and nothing to recover;
    the live poll reads its newest page.
    """
    cursor = get_cursor(conn=conn, space=target.space)
    if cursor is None:
        return ok(SpaceBackfill())
    run = _Run(
        conn=conn,
        reader=reader,
        target=target,
        cursor=cursor,
        now=now,
        limits=limits,
        budget=budget if budget is not None else ReadBudget(remaining=limits.max_reads),
    )
    since = _read_window(run=run)
    if isinstance(since, ErrorResult):
        return since
    start = since.value
    steps: tuple[Callable[[], Result[Any]], ...] = (
        lambda: _backfill_messages(run=run, since=start),
        lambda: _backfill_reactions(run=run),
        lambda: _settle_budget_gap(run=run),
    )
    for step in steps:
        outcome = step()
        if isinstance(outcome, ErrorResult):
            return outcome
    if run.tally.truncated:
        log.warning(
            "Chat backfill of %s used its read budget; the rest continues next run", target.space
        )
    return ok(run.tally.report())


def _recover_subscription(
    *,
    conn: sqlite3.Connection,
    recovery: SubscriptionRecovery | None,
    now: datetime,
) -> tuple[SubscriptionStatus | None, str | None]:
    if recovery is None:
        return None, None
    ensured = ensure_subscription(conn=conn, api=recovery.api, spec=recovery.spec, now=now)
    if isinstance(ensured, ErrorResult):
        # Backfill still runs: what it recovers now is not lost while the
        # subscription waits for a later tick to come back.
        return None, ensured.error
    return ensured.value, None


def catch_up(
    *,
    conn: sqlite3.Connection,
    reader: ChatHistoryReader,
    targets: Sequence[WatchedSpace],
    now: datetime,
    subscription: SubscriptionRecovery | None = None,
    limits: BackfillLimits = BackfillLimits(),
) -> Result[CatchUpReport]:
    """Recover after a start-up or resume; one failing space does not stop the others."""
    spaces = sorted({target.space for target in targets})
    if len(spaces) != len(targets):
        return err("Each watched space must appear once in a backfill run", spaces=spaces)
    status, subscription_error = _recover_subscription(conn=conn, recovery=subscription, now=now)
    ordered = sorted(targets, key=lambda target: target.space)
    read, skipped = ordered[: limits.max_spaces], ordered[limits.max_spaces :]
    if skipped:
        log.warning(
            "Chat backfill watches %d spaces; only the first %d are read",
            len(ordered),
            limits.max_spaces,
        )
    budget = ReadBudget(remaining=limits.max_reads)
    results: dict[str, SpaceBackfill] = {}
    failures: dict[str, str] = {}
    for target in read:
        outcome = backfill_space(
            conn=conn, reader=reader, target=target, now=now, limits=limits, budget=budget
        )
        if isinstance(outcome, ErrorResult):
            log.warning("Chat backfill of %s failed: %s", target.space, outcome.error)
            failures[target.space] = outcome.error
            continue
        results[target.space] = outcome.value
    return ok(
        CatchUpReport(
            subscription=status,
            subscription_error=subscription_error,
            spaces=results,
            failures=failures,
            skipped=tuple(target.space for target in skipped),
        )
    )
