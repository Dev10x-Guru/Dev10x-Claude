from __future__ import annotations

import os
import re
import secrets
import socket
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

BUS_ROOT = Path("/tmp/claude-bus")
SEEN_FLAG = ":2,S"
SLUG_LIMIT = 40
THREAD_SEPARATOR = "--"
INVALID_MESSAGE_EXIT = 2
MAILBOX_NAME = re.compile(r"[A-Za-z0-9]+([._-][A-Za-z0-9]+)*")
HEADER_KEY = re.compile(r"[A-Za-z][A-Za-z0-9-]*")
BUS_HEADERS = frozenset(
    {
        "from",
        "to",
        "date",
        "subject",
        "message-id",
        "in-reply-to",
        "references",
        "reply-to",
        "voice",
    }
)


class InvalidMessageError(ValueError):
    pass


def validate_mailbox_name(field: str, value: str) -> None:
    if not MAILBOX_NAME.fullmatch(value):
        raise InvalidMessageError(
            f"{field} {value!r} is not a mailbox name: use letters and digits "
            "joined by single '.', '-' or '_', with no path separators"
        )


def validate_single_line(field: str, value: str) -> None:
    if "\r" in value or "\n" in value:
        raise InvalidMessageError(f"header {field} must be a single line")


def validate_extra_header(key: str, value: str) -> None:
    if not HEADER_KEY.fullmatch(key):
        raise InvalidMessageError(f"header name {key!r} is not a single token")
    if key.lower() in BUS_HEADERS:
        raise InvalidMessageError(f"header {key} is set by the bus and cannot be overridden")
    validate_single_line(field=key, value=value)


def mailbox_path(root: Path, name: str) -> Path:
    validate_mailbox_name(field="mailbox", value=name)
    return root / name


@dataclass(frozen=True)
class Envelope:
    sender: str
    recipient: str
    subject: str
    reply_to: str | None = None
    in_reply_to: str | None = None
    references: str | None = None
    voice: bool = False
    extra_headers: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        validate_mailbox_name(field="sender", value=self.sender)
        validate_mailbox_name(field="recipient", value=self.recipient)
        if self.reply_to is not None:
            validate_mailbox_name(field="reply_to", value=self.reply_to)
        validate_single_line(field="Subject", value=self.subject)
        validate_single_line(field="In-Reply-To", value=self.in_reply_to or "")
        validate_single_line(field="References", value=self.references or "")
        for key, value in self.extra_headers:
            validate_extra_header(key=key, value=value)


@dataclass(frozen=True)
class Delivery:
    path: Path
    message_id: str


def ensure_maildir(maildir: Path) -> None:
    for part in ("tmp", "new", "cur"):
        (maildir / part).mkdir(parents=True, exist_ok=True)


def target_maildir(
    root: Path,
    sender: str,
    recipient: str,
    thread: bool,
) -> Path:
    if thread:
        pair = THREAD_SEPARATOR.join(sorted((sender, recipient)))
        return root / "threads" / pair
    return mailbox_path(root=root, name=recipient)


def headers_for(
    envelope: Envelope,
    message_id: str,
    sent_at: datetime,
) -> dict[str, str]:
    return {
        "From": envelope.sender,
        "To": envelope.recipient,
        "Date": sent_at.isoformat(timespec="seconds"),
        "Subject": envelope.subject,
        "Message-ID": message_id,
        "In-Reply-To": envelope.in_reply_to or "",
        "References": envelope.references or envelope.in_reply_to or "",
        "Reply-To": envelope.reply_to or envelope.sender,
        "Voice": "yes" if envelope.voice else "",
        **dict(envelope.extra_headers),
    }


def render(headers: dict[str, str], body: str) -> str:
    lines = [f"{key}: {value}" for key, value in headers.items() if value]
    return "---\n" + "\n".join(lines) + "\n---\n\n" + body.rstrip() + "\n"


def slugify(subject: str) -> str:
    raw = "".join(ch if ch.isascii() and ch.isalnum() else "-" for ch in subject.lower())
    return "-".join(part for part in raw.split("-") if part)[:SLUG_LIMIT].strip("-")


def deliver(maildir: Path, name: str, content: str) -> Path:
    ensure_maildir(maildir=maildir)
    draft = maildir / "tmp" / name
    draft.write_text(content, encoding="utf-8")
    return draft.rename(maildir / "new" / name)


def send(
    root: Path,
    envelope: Envelope,
    body: str,
    thread: bool = False,
    sent_at: datetime | None = None,
) -> Delivery:
    now = sent_at or datetime.now().astimezone()
    stamp = now.strftime("%Y%m%dT%H%M%S")
    message_id = f"<{stamp}.{secrets.token_hex(3)}.{envelope.sender}@{socket.gethostname()}>"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = deliver(
        maildir=target_maildir(
            root=root,
            sender=envelope.sender,
            recipient=envelope.recipient,
            thread=thread,
        ),
        name=f"{stamp}.{os.getpid()}.{envelope.sender}.{slugify(subject=envelope.subject)}",
        content=render(
            headers=headers_for(envelope=envelope, message_id=message_id, sent_at=now),
            body=body,
        ),
    )
    return Delivery(path=path, message_id=message_id)


def maildirs_for(root: Path, name: str) -> list[Path]:
    own = [mailbox_path(root=root, name=name)]
    threads = root / "threads"
    if not threads.is_dir():
        return own
    return own + [
        thread
        for thread in sorted(threads.iterdir())
        if name in thread.name.split(THREAD_SEPARATOR)
    ]


def is_unread_message(message: Path) -> bool:
    return message.parent.name == "new" and message.is_file()


def unread(maildirs: list[Path]) -> set[Path]:
    return {
        message
        for maildir in maildirs
        if (maildir / "new").is_dir()
        for message in (maildir / "new").iterdir()
        if is_unread_message(message=message)
    }


def mark_read(message: Path) -> Path:
    cur = message.parent.parent / "cur"
    cur.mkdir(parents=True, exist_ok=True)
    return message.rename(cur / f"{message.name}{SEEN_FLAG}")


def done_targets(root: Path, args: list[str]) -> list[Path]:
    targets: list[Path] = []
    for arg in args:
        if "/" in arg:
            targets.append(message_under_root(root=root, raw=arg))
        else:
            targets.extend(mailbox_unread(root=root, name=arg))
    return targets


def message_under_root(root: Path, raw: str) -> Path:
    message = root / raw
    if not message.resolve().is_relative_to(root.resolve()):
        raise InvalidMessageError(f"{raw!r} is outside the bus root {root}")
    return message


def mailbox_unread(root: Path, name: str) -> list[Path]:
    new = mailbox_path(root=root, name=name) / "new"
    if not new.is_dir():
        raise InvalidMessageError(f"mailbox {name!r} has no new/ under {root}")
    return sorted(new.glob("*"))
