"""Chat bus authorization: who may make the bus do what (ADR-0035 D2, D3).

The verdict is computed here, in code, from the stored event and the
``bus_role`` allowlist. Message text is untrusted data: it selects a
verb, never a role, and nothing in this module writes the config the
allowlist comes from. Every event takes the same path whatever its
source, so a backfilled or replayed event is checked like a live one.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from dev10x.comm.chatbus.events import (
    EVENT_TYPES,
    MESSAGE_CREATED,
    REACTION_CREATED,
    REACTION_DELETED,
    resource_space,
    to_db_time,
)
from dev10x.comm.chatbus.queue import WorkKind, WorkStatus
from dev10x.comm.chatbus.store import write_transaction
from dev10x.comm.skills.notifications.gchat_users import BusRole, ChatUser, load_chat_users
from dev10x.domain.common.result import ErrorResult, Result, err, ok

log = logging.getLogger(__name__)

PRIVILEGED_COMMANDS = frozenset({"start", "implement", "ticket"})
PRIVILEGED_REACTIONS: Mapping[str, str] = {"🎫": "ticket", "🤖": "start"}
APPROVE_COMMAND = "approve"
APPROVE_REACTION = "✅"
REPLY_VERB = "reply"


class Outcome(StrEnum):
    IGNORED = "ignored"
    REPLY = "reply"
    REJECTED = "rejected"
    AWAITING_APPROVAL = "awaiting_approval"
    QUEUED = "queued"
    APPROVED = "approved"


class Action(StrEnum):
    IGNORE = "ignore"
    REPLY = "reply"
    PRIVILEGED = "privileged"
    APPROVE = "approve"
    INVALID = "invalid"


@dataclass(frozen=True)
class Allowlist:
    owner: str
    trusted: frozenset[str]
    logins: Mapping[str, str]

    def role_of(self, *, sender: str) -> BusRole | None:
        if sender == self.owner:
            return BusRole.OWNER
        if sender in self.trusted:
            return BusRole.TRUSTED
        return None

    def describe(self) -> str:
        def label(user: str) -> str:
            return f"{self.logins.get(user, '?')} ({user})"

        trusted = ", ".join(label(user) for user in sorted(self.trusted)) or "none"
        return f"owner={label(self.owner)}; trusted={trusted}"


def build_allowlist(*, users: Sequence[ChatUser]) -> Result[Allowlist]:
    """Exactly one owner, or no allowlist at all (the daemon must not start)."""
    roles: dict[str, BusRole] = {}
    logins: dict[str, str] = {}
    for user in users:
        if user.bus_role is None or user.chat_user is None:
            continue
        known = roles.get(user.chat_user)
        if known is not None and known != user.bus_role:
            return err(
                f"Chat user {user.chat_user} is listed as both {known.value} and "
                f"{user.bus_role.value}; fix gchat-config.yaml users:",
                chat_user=user.chat_user,
            )
        roles[user.chat_user] = user.bus_role
        logins.setdefault(user.chat_user, user.login)
    owners = sorted(chat_user for chat_user, role in roles.items() if role is BusRole.OWNER)
    if len(owners) != 1:
        return err(
            "The Chat bus needs exactly one user with bus_role: owner in gchat-config.yaml "
            f"users:, found {len(owners)}",
            owners=owners,
        )
    trusted = frozenset(user for user, role in roles.items() if role is BusRole.TRUSTED)
    return ok(Allowlist(owner=owners[0], trusted=trusted, logins=logins))


def load_allowlist(*, path: Path, reason: str) -> Result[Allowlist]:
    """Load and log the effective allowlist; call at daemon start and on reload."""
    users = load_chat_users(path=path)
    if isinstance(users, ErrorResult):
        return users
    allowlist = build_allowlist(users=users.value)
    if isinstance(allowlist, ErrorResult):
        log.error("Chat bus allowlist rejected (%s): %s", reason, allowlist.error)
        return allowlist
    log.info("Chat bus allowlist (%s): %s", reason, allowlist.value.describe())
    return allowlist


class ApprovalNotifier(Protocol):
    def request_approval(
        self,
        *,
        owner: str,
        work_item_id: int,
        requester: str,
        verb: str,
    ) -> Result[str]:
        """Send the owner an approval DM and return its message resource name."""


@dataclass(frozen=True)
class Intent:
    actor: str
    action: Action
    verb: str
    reason: str = ""
    is_reaction: bool = False
    approve_item: int | None = None
    approve_dm: str | None = None


@dataclass(frozen=True)
class Verdict:
    event_id: int
    outcome: Outcome
    actor: str
    verb: str
    reason: str
    work_item_id: int | None = None
    approval_dm: str | None = None
    replayed: bool = False


@dataclass(frozen=True)
class EventRow:
    id: int
    type: str
    space: str
    resource_name: str
    sender: str
    payload: Mapping[str, Any]


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _is_direct_message(*, message: Mapping[str, Any]) -> bool:
    space = _mapping(message.get("space"))
    return space.get("spaceType") == "DIRECT_MESSAGE" or space.get("type") == "DM"


def _mentions(*, message: Mapping[str, Any], user: str) -> bool:
    annotations = message.get("annotations")
    if not isinstance(annotations, list):
        return False
    for annotation in annotations:
        entry = _mapping(annotation)
        mentioned = _mapping(_mapping(entry.get("userMention")).get("user")).get("name")
        if entry.get("type") == "USER_MENTION" and mentioned == user:
            return True
    return False


def _invalid(*, actor: str, verb: str, reason: str) -> Intent:
    return Intent(actor=actor, action=Action.INVALID, verb=verb, reason=reason)


def _command_text(*, message: Mapping[str, Any]) -> str:
    # argumentText is the text with the bot mention removed.
    for key in ("argumentText", "text"):
        value = message.get(key)
        if isinstance(value, str):
            return value
    return ""


def _classify_message(*, actor: str, message: Mapping[str, Any], bot_user: str) -> Intent:
    direct = _is_direct_message(message=message)
    if not (direct or _mentions(message=message, user=bot_user)):
        return Intent(actor=actor, action=Action.IGNORE, verb="", reason="not addressed to bot")
    tokens = _command_text(message=message).split()
    first = tokens[0].lower() if tokens else ""
    if first == APPROVE_COMMAND:
        if not direct:
            return _invalid(
                actor=actor, verb=first, reason="approvals count only in a DM with the bot"
            )
        if len(tokens) != 2 or not (tokens[1].isascii() and tokens[1].isdigit()):
            return _invalid(actor=actor, verb=first, reason="approve takes one work item id")
        return Intent(actor=actor, action=Action.APPROVE, verb=first, approve_item=int(tokens[1]))
    if first in PRIVILEGED_COMMANDS:
        return Intent(actor=actor, action=Action.PRIVILEGED, verb=first)
    return Intent(actor=actor, action=Action.REPLY, verb=REPLY_VERB)


def _classify_reaction(*, actor: str, reaction: Mapping[str, Any], name: str) -> Intent:
    emoji = _mapping(reaction.get("emoji")).get("unicode")
    if isinstance(emoji, str) and emoji in PRIVILEGED_REACTIONS:
        return Intent(
            actor=actor,
            action=Action.PRIVILEGED,
            verb=PRIVILEGED_REACTIONS[emoji],
            is_reaction=True,
        )
    if emoji == APPROVE_REACTION:
        return Intent(
            actor=actor,
            action=Action.APPROVE,
            verb=APPROVE_COMMAND,
            is_reaction=True,
            approve_dm=name.rsplit("/reactions/", 1)[0],
        )
    return Intent(actor=actor, action=Action.IGNORE, verb="", reason="not a bus reaction")


def classify(*, event: EventRow, bot_user: str) -> Intent:
    """Turn a stored event into what its sender asks for; never decides authority."""
    actor = event.sender
    if event.type not in EVENT_TYPES:
        return _invalid(actor=actor, verb="", reason=f"unknown event type {event.type}")
    if resource_space(event_type=event.type, resource_name=event.resource_name) != event.space:
        return _invalid(actor=actor, verb="", reason="resource name does not match its space")
    if event.type == REACTION_DELETED:
        return Intent(actor=actor, action=Action.IGNORE, verb="", reason="reaction removed")
    key = "message" if event.type == MESSAGE_CREATED else "reaction"
    resource = _mapping(event.payload.get(key))
    if resource.get("name") != event.resource_name:
        return _invalid(actor=actor, verb="", reason=f"payload {key} does not match the event")
    person = "sender" if key == "message" else "user"
    if _mapping(resource.get(person)).get("name") != event.sender:
        return _invalid(actor=actor, verb="", reason=f"payload {person} does not match the event")
    if event.sender == bot_user:
        return Intent(actor=actor, action=Action.IGNORE, verb="", reason="the bot's own event")
    if event.type == REACTION_CREATED:
        return _classify_reaction(actor=actor, reaction=resource, name=event.resource_name)
    return _classify_message(actor=actor, message=resource, bot_user=bot_user)


def _load_event(*, conn: sqlite3.Connection, event_id: int) -> Result[EventRow]:
    row = conn.execute(
        "SELECT id, type, space, resource_name, sender, payload FROM events WHERE id = ?",
        (event_id,),
    ).fetchone()
    if row is None:
        return err(f"No Chat bus event {event_id}", event_id=event_id)
    try:
        payload = json.loads(row["payload"])
    except json.JSONDecodeError:
        payload = {}
    return ok(
        EventRow(
            id=row["id"],
            type=row["type"],
            space=row["space"],
            resource_name=row["resource_name"],
            sender=row["sender"],
            payload=_mapping(payload),
        )
    )


def _recorded(*, conn: sqlite3.Connection, event_id: int) -> Verdict | None:
    row = conn.execute(
        "SELECT actor, verb, reason, outcome, work_item_id FROM commands WHERE event_id = ?",
        (event_id,),
    ).fetchone()
    if row is None:
        return None
    return Verdict(
        event_id=event_id,
        outcome=Outcome(row["outcome"]),
        actor=row["actor"],
        verb=row["verb"],
        reason=row["reason"],
        work_item_id=row["work_item_id"],
        replayed=True,
    )


def _record(*, conn: sqlite3.Connection, verdict: Verdict, stamp: str) -> None:
    authorized = verdict.outcome is not Outcome.REJECTED
    conn.execute(
        """
        INSERT INTO commands (
            event_id, actor, verb, authorized, reason, created_at, outcome, work_item_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            verdict.event_id,
            verdict.actor,
            verdict.verb,
            int(authorized),
            verdict.reason,
            stamp,
            verdict.outcome.value,
            verdict.work_item_id,
        ),
    )


def _add_work_item(
    *,
    conn: sqlite3.Connection,
    event_id: int,
    kind: WorkKind,
    status: WorkStatus,
    stamp: str,
) -> int:
    row = conn.execute(
        """
        INSERT INTO work_items (event_id, kind, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        RETURNING id
        """,
        (event_id, kind.value, status.value, stamp, stamp),
    ).fetchone()
    return int(row[0])


def _approval_target(*, conn: sqlite3.Connection, intent: Intent) -> int | None:
    if intent.action is not Action.APPROVE:
        return None
    if intent.approve_item is not None:
        return intent.approve_item
    row = conn.execute(
        "SELECT work_item_id FROM approvals WHERE dm_message = ?", (intent.approve_dm,)
    ).fetchone()
    return None if row is None else int(row[0])


def _approve(
    *,
    conn: sqlite3.Connection,
    event_id: int,
    intent: Intent,
    item_id: int,
    stamp: str,
) -> Verdict:
    released = conn.execute(
        """
        UPDATE work_items SET status = 'queued', updated_at = ?
         WHERE id = ? AND kind = 'privileged' AND status = 'awaiting_approval'
        RETURNING id
        """,
        (stamp, item_id),
    ).fetchone()
    if released is None:
        return Verdict(
            event_id=event_id,
            outcome=Outcome.REJECTED,
            actor=intent.actor,
            verb=intent.verb,
            reason=f"work item {item_id} is not awaiting approval",
        )
    conn.execute(
        "UPDATE approvals SET approved_by_event = ?, approved_at = ? WHERE work_item_id = ?",
        (event_id, stamp, item_id),
    )
    return Verdict(
        event_id=event_id,
        outcome=Outcome.APPROVED,
        actor=intent.actor,
        verb=intent.verb,
        reason="owner approved",
        work_item_id=item_id,
    )


def _decide(
    *,
    conn: sqlite3.Connection,
    event_id: int,
    intent: Intent,
    role: BusRole | None,
    stamp: str,
) -> Verdict:
    def verdict(*, outcome: Outcome, reason: str, item: int | None = None) -> Verdict:
        return Verdict(
            event_id=event_id,
            outcome=outcome,
            actor=intent.actor,
            verb=intent.verb,
            reason=reason,
            work_item_id=item,
        )

    def add(*, kind: WorkKind, status: WorkStatus) -> int:
        return _add_work_item(conn=conn, event_id=event_id, kind=kind, status=status, stamp=stamp)

    target = _approval_target(conn=conn, intent=intent)
    match intent.action:
        case Action.IGNORE:
            return verdict(outcome=Outcome.IGNORED, reason=intent.reason)
        case Action.APPROVE if target is None:
            # A ✅ on any message but an approval DM is ordinary chat.
            return verdict(outcome=Outcome.IGNORED, reason="not an approval request")
        case Action.INVALID:
            return verdict(outcome=Outcome.REJECTED, reason=intent.reason)
        case Action.REPLY:
            return verdict(
                outcome=Outcome.REPLY,
                reason="anyone may ask for a reply",
                item=add(kind=WorkKind.REPLY, status=WorkStatus.QUEUED),
            )
        case Action.PRIVILEGED if role is BusRole.OWNER:
            return verdict(
                outcome=Outcome.QUEUED,
                reason="owner signal",
                item=add(kind=WorkKind.PRIVILEGED, status=WorkStatus.QUEUED),
            )
        case Action.PRIVILEGED if role is BusRole.TRUSTED and not intent.is_reaction:
            item = add(kind=WorkKind.PRIVILEGED, status=WorkStatus.AWAITING_APPROVAL)
            conn.execute(
                "INSERT INTO approvals (work_item_id, requested_at) VALUES (?, ?)",
                (item, stamp),
            )
            return verdict(
                outcome=Outcome.AWAITING_APPROVAL,
                reason="trusted user; owner approval needed",
                item=item,
            )
        case Action.PRIVILEGED if role is BusRole.TRUSTED:
            return verdict(
                outcome=Outcome.REJECTED, reason="only the owner's reactions trigger work"
            )
        case Action.PRIVILEGED:
            return verdict(outcome=Outcome.REJECTED, reason="sender is not on the bus allowlist")
        case Action.APPROVE if role is BusRole.OWNER and target is not None:
            return _approve(
                conn=conn, event_id=event_id, intent=intent, item_id=target, stamp=stamp
            )
        case _:
            return verdict(
                outcome=Outcome.REJECTED, reason="only the owner approves privileged work"
            )


def _send_approval_request(
    *,
    conn: sqlite3.Connection,
    verdict: Verdict,
    item_id: int,
    allowlist: Allowlist,
    notifier: ApprovalNotifier,
) -> Verdict:
    sent = notifier.request_approval(
        owner=allowlist.owner,
        work_item_id=item_id,
        requester=verdict.actor,
        verb=verdict.verb,
    )
    if isinstance(sent, ErrorResult):
        log.error("Approval DM for work item %s was not sent: %s", item_id, sent.error)
        return verdict
    try:
        with write_transaction(conn=conn) as tx:
            tx.execute(
                "UPDATE approvals SET dm_message = ? WHERE work_item_id = ?",
                (sent.value, item_id),
            )
    except sqlite3.Error as exc:
        log.error("Cannot record the approval DM for work item %s: %s", item_id, exc)
        return verdict
    return replace(verdict, approval_dm=sent.value)


def authorize(
    *,
    conn: sqlite3.Connection,
    event_id: int,
    allowlist: Allowlist,
    bot_user: str,
    notifier: ApprovalNotifier,
    now: datetime,
) -> Result[Verdict]:
    """Decide one stored event; an already-decided event returns its first verdict."""
    stamp = to_db_time(moment=now)
    try:
        with write_transaction(conn=conn) as tx:
            recorded = _recorded(conn=tx, event_id=event_id)
            if recorded is not None:
                return ok(recorded)
            event = _load_event(conn=tx, event_id=event_id)
            if isinstance(event, ErrorResult):
                return event
            intent = classify(event=event.value, bot_user=bot_user)
            verdict = _decide(
                conn=tx,
                event_id=event_id,
                intent=intent,
                role=allowlist.role_of(sender=intent.actor),
                stamp=stamp,
            )
            if verdict.outcome is Outcome.IGNORED:
                return ok(verdict)
            _record(conn=tx, verdict=verdict, stamp=stamp)
    except sqlite3.Error as exc:
        log.error("Chat bus authorization failed for event %s: %s", event_id, exc)
        return err(f"Chat bus authorization failed for event {event_id}: {exc}", event_id=event_id)
    log.info(
        "Chat bus event %s from %s: %s %s (%s)",
        event_id,
        verdict.actor,
        verdict.verb or "-",
        verdict.outcome.value,
        verdict.reason,
    )
    if verdict.outcome is Outcome.AWAITING_APPROVAL and verdict.work_item_id is not None:
        return ok(
            _send_approval_request(
                conn=conn,
                verdict=verdict,
                item_id=verdict.work_item_id,
                allowlist=allowlist,
                notifier=notifier,
            )
        )
    return ok(verdict)
