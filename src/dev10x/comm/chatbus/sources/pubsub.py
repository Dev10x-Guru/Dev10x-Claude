"""Pub/Sub pull source: Chat reactions from a Workspace Events subscription (ADR-0035 D1).

A Workspace Events subscription on every Chat space publishes
``reaction.created`` / ``reaction.deleted`` with ``includeResource`` to
a Pub/Sub topic, plus the ``batchCreated`` / ``batchDeleted`` batches
Google adds unasked, which are expanded into their member events. The
daemon pulls from that topic, so events queue in Pub/Sub while the
machine sleeps, and acks a message only after all of its events are
committed. A subscription carrying resource data lapses after
4 hours, so the renewal tick renews it hourly and recreates it once it
has lapsed. The subscription it manages is kept in the store, so a
restart renews the same one instead of creating another.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

from dev10x.comm.chatbus.events import (
    BATCH_MEMBER_TYPES,
    REACTION_CREATED,
    REACTION_DELETED,
    ChatEvent,
    EventSource,
    from_db_time,
    resource_space,
    to_db_time,
)
from dev10x.comm.chatbus.ingest import ingest_events
from dev10x.comm.chatbus.snapshot import remember_reactions
from dev10x.comm.chatbus.store import write_transaction
from dev10x.comm.skills.notifications.gchat_watch import parse_time
from dev10x.domain.common.result import ErrorResult, Result, err, ok

log = logging.getLogger(__name__)

ALL_SPACES = "//chat.googleapis.com/spaces/-"
RENEW_EVERY = timedelta(hours=1)
PULL_BATCH = 100
ACTIVE = "ACTIVE"
SUSPENDED = "SUSPENDED"


@dataclass(frozen=True)
class ReceivedMessage:
    ack_id: str
    data: bytes
    attributes: Mapping[str, str] = field(default_factory=dict)
    publish_time: datetime | None = None


@dataclass(frozen=True)
class SubscriptionSpec:
    topic: str
    target_resource: str = ALL_SPACES
    event_types: tuple[str, ...] = (REACTION_CREATED, REACTION_DELETED)
    include_resource: bool = True


@dataclass(frozen=True)
class SubscriptionState:
    name: str
    state: str
    expire_time: datetime


class PubSubPuller(Protocol):
    def pull(self, *, subscription: str, max_messages: int) -> Result[list[ReceivedMessage]]: ...

    def ack(self, *, subscription: str, ack_ids: Sequence[str]) -> Result[None]: ...


class SubscriptionApi(Protocol):
    def get(self, *, name: str) -> Result[SubscriptionState | None]: ...

    def create(self, *, spec: SubscriptionSpec) -> Result[SubscriptionState]: ...

    def renew(self, *, name: str) -> Result[SubscriptionState]: ...

    def reactivate(self, *, name: str) -> Result[SubscriptionState]: ...


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _reaction_event(
    *,
    event_type: str,
    reaction: Mapping[str, Any],
    moment: datetime,
) -> ChatEvent | None:
    name = reaction.get("name")
    if not isinstance(name, str):
        return None
    space = resource_space(event_type=event_type, resource_name=name)
    if space is None:
        return None
    try:
        return ChatEvent(
            type=event_type,
            resource_name=name,
            space=space,
            sender=str(_mapping(reaction.get("user")).get("name") or ""),
            event_time=moment,
            payload={"reaction": dict(reaction)},
            source=EventSource.PUBSUB,
        )
    except ValueError as exc:
        log.warning("Skipping a Pub/Sub Chat event the bus cannot hold: %s", exc)
        return None


def _member_reactions(*, event_type: str, payload: object) -> list[Mapping[str, Any]]:
    if event_type in BATCH_MEMBER_TYPES:
        members = _mapping(payload).get("reactions")
        if not isinstance(members, list):
            return []
        return [_mapping(_mapping(member).get("reaction")) for member in members]
    return [_mapping(_mapping(payload).get("reaction"))]


@dataclass(frozen=True)
class Unpacked:
    events: list[ChatEvent] = field(default_factory=list)
    skipped_members: int = 0


def events_from_pubsub(*, message: ReceivedMessage) -> Unpacked:
    """The Workspace Events a Pub/Sub message carries, a batch expanded; no events if unusable."""
    event_type = message.attributes.get("ce-type", "")
    single_type = BATCH_MEMBER_TYPES.get(event_type, event_type)
    if single_type not in (REACTION_CREATED, REACTION_DELETED):
        return Unpacked()
    moment = parse_time(raw=message.attributes.get("ce-time", "")) or message.publish_time
    if moment is None:
        return Unpacked()
    try:
        payload = json.loads(message.data or b"null")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return Unpacked()
    built = [
        _reaction_event(event_type=single_type, reaction=reaction, moment=moment)
        for reaction in _member_reactions(event_type=event_type, payload=payload)
    ]
    events = [event for event in built if event is not None]
    return Unpacked(events=events, skipped_members=len(built) - len(events))


@dataclass(frozen=True)
class PullReport:
    pulled: int
    inserted: int
    duplicates: int
    malformed: int
    acked: int
    failed_spaces: tuple[str, ...] = ()
    dropped_by_type: Mapping[str, int] = field(default_factory=dict)
    skipped_members_by_type: Mapping[str, int] = field(default_factory=dict)


def _ack(
    *,
    puller: PubSubPuller,
    subscription: str,
    ack_ids: Sequence[str],
) -> int:
    if not ack_ids:
        return 0
    acked = puller.ack(subscription=subscription, ack_ids=ack_ids)
    if isinstance(acked, ErrorResult):
        # Unacked messages are redelivered and ingest is idempotent.
        log.error("Pub/Sub ack failed for %d message(s): %s", len(ack_ids), acked.error)
        return 0
    return len(ack_ids)


def pull_once(
    *,
    conn: sqlite3.Connection,
    puller: PubSubPuller,
    subscription: str,
    now: datetime,
    max_messages: int = PULL_BATCH,
) -> Result[PullReport]:
    """Pull one batch, store it, and ack only what was committed."""
    pulled = puller.pull(subscription=subscription, max_messages=max_messages)
    if isinstance(pulled, ErrorResult):
        return pulled
    by_space: dict[str, list[ChatEvent]] = {}
    spaces_of: dict[str, set[str]] = {}
    # A message that can never become an event is acked, or it would be
    # redelivered forever.
    ack_ids: list[str] = []
    dropped: Counter[str] = Counter()
    skipped: Counter[str] = Counter()
    for message in pulled.value:
        event_type = message.attributes.get("ce-type", "")
        unpacked = events_from_pubsub(message=message)
        if not unpacked.events:
            log.warning(
                "Dropping an unusable Pub/Sub Chat message %s (%s)",
                message.ack_id,
                event_type or "no ce-type",
            )
            dropped[event_type] += 1
            ack_ids.append(message.ack_id)
            continue
        if unpacked.skipped_members:
            log.warning(
                "Skipping %d unusable member(s) of Pub/Sub Chat message %s (%s)",
                unpacked.skipped_members,
                message.ack_id,
                event_type,
            )
            skipped[event_type] += unpacked.skipped_members
        for event in unpacked.events:
            by_space.setdefault(event.space, []).append(event)
        spaces_of[message.ack_id] = {event.space for event in unpacked.events}
    inserted = duplicates = 0
    failed: list[str] = []
    for space, space_events in sorted(by_space.items()):
        stored = ingest_events(conn=conn, space=space, events=space_events, now=now)
        if isinstance(stored, ErrorResult):
            failed.append(space)
            continue
        # A failed snapshot write only weakens deletion inference until the
        # next backfill re-diffs, so the committed events are still acked.
        remember_reactions(conn=conn, events=space_events, now=now)
        inserted += stored.value.inserted
        duplicates += stored.value.duplicates
    # GH-1948
    ack_ids += [ack_id for ack_id, spaces in spaces_of.items() if spaces.isdisjoint(failed)]
    return ok(
        PullReport(
            pulled=len(pulled.value),
            inserted=inserted,
            duplicates=duplicates,
            malformed=sum(dropped.values()),
            acked=_ack(puller=puller, subscription=subscription, ack_ids=ack_ids),
            failed_spaces=tuple(failed),
            dropped_by_type=dict(dropped),
            skipped_members_by_type=dict(skipped),
        )
    )


class RenewalAction(StrEnum):
    CREATED = "created"
    RECREATED = "recreated"
    RENEWED = "renewed"
    REACTIVATED = "reactivated"


@dataclass(frozen=True)
class SubscriptionStatus:
    name: str
    expire_time: datetime
    action: RenewalAction


@dataclass(frozen=True)
class StoredSubscription:
    name: str
    expire_time: datetime
    renewed_at: datetime


def get_subscription(*, conn: sqlite3.Connection, target: str) -> StoredSubscription | None:
    row = conn.execute(
        "SELECT name, expire_time, renewed_at FROM subscriptions WHERE target = ?",
        (target,),
    ).fetchone()
    if row is None:
        return None
    return StoredSubscription(
        name=row[0],
        expire_time=from_db_time(value=row[1]),
        renewed_at=from_db_time(value=row[2]),
    )


def renewal_due(
    *,
    conn: sqlite3.Connection,
    target: str,
    now: datetime,
    every: timedelta = RENEW_EVERY,
) -> bool:
    stored = get_subscription(conn=conn, target=target)
    return stored is None or stored.renewed_at + every <= now or stored.expire_time <= now


def _save(
    *,
    conn: sqlite3.Connection,
    target: str,
    state: SubscriptionState,
    now: datetime,
) -> None:
    with write_transaction(conn=conn) as tx:
        tx.execute(
            """
            INSERT INTO subscriptions (target, name, expire_time, renewed_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (target) DO UPDATE SET
                name = excluded.name,
                expire_time = excluded.expire_time,
                renewed_at = excluded.renewed_at
            """,
            (target, state.name, to_db_time(moment=state.expire_time), to_db_time(moment=now)),
        )


def _refresh(
    *,
    api: SubscriptionApi,
    spec: SubscriptionSpec,
    stored: StoredSubscription | None,
    now: datetime,
) -> Result[tuple[SubscriptionState, RenewalAction]]:
    if stored is None:
        created = api.create(spec=spec)
        if isinstance(created, ErrorResult):
            return created
        return ok((created.value, RenewalAction.CREATED))
    current = api.get(name=stored.name)
    if isinstance(current, ErrorResult):
        return current
    live = current.value
    if live is None or live.expire_time <= now or live.state not in (ACTIVE, SUSPENDED):
        recreated = api.create(spec=spec)
        if isinstance(recreated, ErrorResult):
            return recreated
        return ok((recreated.value, RenewalAction.RECREATED))
    if live.state == SUSPENDED:
        reactivated = api.reactivate(name=live.name)
        if isinstance(reactivated, ErrorResult):
            return reactivated
        return ok((reactivated.value, RenewalAction.REACTIVATED))
    renewed = api.renew(name=live.name)
    if isinstance(renewed, ErrorResult):
        return renewed
    return ok((renewed.value, RenewalAction.RENEWED))


def ensure_subscription(
    *,
    conn: sqlite3.Connection,
    api: SubscriptionApi,
    spec: SubscriptionSpec,
    now: datetime,
) -> Result[SubscriptionStatus]:
    """Renew the managed subscription, or recreate it when it has lapsed."""
    stored = get_subscription(conn=conn, target=spec.target_resource)
    refreshed = _refresh(api=api, spec=spec, stored=stored, now=now)
    if isinstance(refreshed, ErrorResult):
        log.error("Workspace Events subscription refresh failed: %s", refreshed.error)
        return refreshed
    state, action = refreshed.value
    try:
        _save(conn=conn, target=spec.target_resource, state=state, now=now)
    except sqlite3.Error as exc:
        log.error("Cannot record the Workspace Events subscription %s: %s", state.name, exc)
        return err(f"Cannot record the Workspace Events subscription {state.name}: {exc}")
    if action is RenewalAction.RECREATED:
        log.warning("Workspace Events subscription had lapsed; recreated as %s", state.name)
    return ok(SubscriptionStatus(name=state.name, expire_time=state.expire_time, action=action))
