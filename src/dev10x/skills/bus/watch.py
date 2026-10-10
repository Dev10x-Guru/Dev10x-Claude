from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path

from dev10x.skills.bus.maildir import (
    BUS_ROOT,
    INVALID_MESSAGE_EXIT,
    InvalidMessageError,
    maildirs_for,
    unread,
    validate_mailbox_name,
)

POLL_INTERVAL_SECONDS = 1.0


def arrivals(
    root: Path,
    name: str,
    interval: float,
    sleep: Callable[[float], None] | None = None,
) -> Iterator[list[Path]]:
    pause = sleep or time.sleep
    seen = unread(maildirs=maildirs_for(root=root, name=name))
    while True:
        pause(interval)
        current = unread(maildirs=maildirs_for(root=root, name=name))
        yield sorted(current - seen)
        seen = current


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Print 'NEW <path>' for each message arriving in a claude-bus mailbox."
    )
    parser.add_argument("name", help="mailbox name to watch (threads included)")
    parser.add_argument("--root", type=Path, default=BUS_ROOT, help=argparse.SUPPRESS)
    parser.add_argument(
        "--interval", type=float, default=POLL_INTERVAL_SECONDS, help=argparse.SUPPRESS
    )
    parser.add_argument("--polls", type=int, default=None, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_mailbox_name(field="mailbox", value=args.name)
    except InvalidMessageError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return INVALID_MESSAGE_EXIT
    for poll, batch in enumerate(
        arrivals(root=args.root, name=args.name, interval=args.interval), start=1
    ):
        for message in batch:
            print(f"NEW {message}", flush=True)
        if args.polls is not None and poll >= args.polls:
            break
    return 0
