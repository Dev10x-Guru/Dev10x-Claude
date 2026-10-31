from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from dev10x.comm.skills.bus.maildir import Envelope, send
from dev10x.comm.supervisor.probes import send_keys
from dev10x.domain.file_locks import atomic_append_line

PREAPPROVE_SCOPES = ("worktree", "repo-checkouts", "user-global", "dev10x-catalog")
RELAY_MAILBOX = "supervisor-relay"
SENDER_MAILBOX = "supervisor"
ANSWER_PREFIX = "Answer from Janusz: "


def keys_for_option(*, index: int) -> list[str]:
    return [str(index + 1)]


def _log(*, log_path: Path, action: str, target: str, detail: str, confirmed_by: str) -> None:
    record = {
        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "action": action,
        "target": target,
        "detail": detail,
        "confirmed_by": confirmed_by,
    }
    atomic_append_line(log_path, json.dumps(record))


def deliver_keys(
    *,
    pane_id: str,
    keys: list[str],
    confirmed_by: str,
    log_path: Path,
    sender: Callable[..., None] = send_keys,
) -> None:
    sender(pane_id=pane_id, keys=keys)
    _log(
        log_path=log_path,
        action="keys",
        target=pane_id,
        detail=" ".join(keys),
        confirmed_by=confirmed_by,
    )


def request_preapproval(
    *,
    bus_root: Path,
    relay_mailbox: str,
    session_name: str,
    session_id: str,
    cwd: str,
    request_id: str,
    pending: dict[str, Any] | None,
    commands: list[str],
    confirmed_by: str,
    log_path: Path,
) -> Path:
    body = {
        "session": {"id": session_id, "name": session_name, "cwd": cwd},
        "pending": pending,
        "commands": commands,
        "scopes": list(PREAPPROVE_SCOPES),
    }
    delivery = send(
        root=bus_root,
        envelope=Envelope(
            sender=SENDER_MAILBOX,
            recipient=relay_mailbox,
            subject=f"preapprove {request_id}",
            extra_headers=(
                ("To-Session", session_name),
                ("Session-Id", session_id),
                ("Request-Id", request_id),
            ),
        ),
        body=json.dumps(body, indent=2),
    )
    _log(
        log_path=log_path,
        action="preapprove",
        target=session_name,
        detail=f"{request_id}: {len(commands)} commands",
        confirmed_by=confirmed_by,
    )
    return delivery.path


def deliver_relay(
    *,
    bus_root: Path,
    relay_mailbox: str,
    session_name: str,
    session_id: str,
    decision_id: str,
    answer: str,
    confirmed_by: str,
    log_path: Path,
) -> Path:
    delivery = send(
        root=bus_root,
        envelope=Envelope(
            sender=SENDER_MAILBOX,
            recipient=relay_mailbox,
            subject=f"answer {decision_id}",
            extra_headers=(
                ("To-Session", session_name),
                ("Session-Id", session_id),
                ("Decision-Id", decision_id),
            ),
        ),
        body=ANSWER_PREFIX + answer,
    )
    _log(
        log_path=log_path,
        action="relay",
        target=session_name,
        detail=f"{decision_id}: {answer}",
        confirmed_by=confirmed_by,
    )
    return delivery.path
