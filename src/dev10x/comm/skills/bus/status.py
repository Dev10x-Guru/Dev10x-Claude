from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from dev10x.comm.skills.bus.maildir import (
    BUS_ROOT,
    INVALID_MESSAGE_EXIT,
    STATES,
    Envelope,
    InvalidMessageError,
    SessionStatus,
    send,
    write_status,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish this session's state to the claude-bus status board."
    )
    parser.add_argument("name", help="this session's mailbox name")
    parser.add_argument("state", choices=STATES)
    parser.add_argument("summary", help="one sentence a listener can act on")
    parser.add_argument("--callsign", default="", help="stable spoken name, e.g. 'login fix'")
    parser.add_argument(
        "--notify",
        action="append",
        default=[],
        metavar="MAILBOX",
        help="also drop a short notice into this mailbox (repeatable)",
    )
    parser.add_argument("--root", type=Path, default=BUS_ROOT, help=argparse.SUPPRESS)
    return parser


def notice_envelope(status: SessionStatus, recipient: str) -> Envelope:
    return Envelope(
        sender=status.mailbox,
        recipient=recipient,
        subject=f"{status.callsign or status.mailbox}: {status.state}",
        extra_headers=(("State", status.state), ("Callsign", status.callsign)),
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        status = SessionStatus(
            mailbox=args.name,
            state=args.state,
            summary=args.summary,
            updated=datetime.now().astimezone(),
            callsign=args.callsign,
        )
        notices = [
            notice_envelope(status=status, recipient=recipient) for recipient in args.notify
        ]
    except InvalidMessageError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return INVALID_MESSAGE_EXIT
    print(f"STATUS {write_status(root=args.root, status=status)}")
    for envelope in notices:
        delivery = send(root=args.root, envelope=envelope, body=status.summary)
        print(f"SENT {delivery.path}")
    return 0
