from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable, Iterable, Iterator
from datetime import datetime
from pathlib import Path

from dev10x.comm.skills.bus.maildir import (
    BUS_ROOT,
    INVALID_MESSAGE_EXIT,
    DuplicateFilter,
    InboundPolicy,
    InvalidMessageError,
    is_own_thread_message,
    maildirs_for,
    screen_message,
    unread,
    validate_mailbox_name,
)

POLL_INTERVAL_SECONDS = 1.0


def arrivals(
    root: Path,
    name: str,
    interval: float,
    sleep: Callable[[float], None] | None = None,
    seen: set[Path] | None = None,
) -> Iterator[list[Path]]:
    pause = sleep or time.sleep
    if seen is None:
        seen = unread(maildirs=maildirs_for(root=root, name=name))
    while True:
        pause(interval)
        current = unread(maildirs=maildirs_for(root=root, name=name))
        yield sorted(current - seen)
        seen = current


def next_batch(
    root: Path,
    name: str,
    interval: float,
    polls: int | None = None,
    sleep: Callable[[float], None] | None = None,
) -> list[Path]:
    pending = unread(maildirs=maildirs_for(root=root, name=name))
    batch = inbound(messages=pending, name=name)
    batches = arrivals(root=root, name=name, interval=interval, sleep=sleep, seen=pending)
    poll = 0
    while not batch and (polls is None or poll < polls):
        batch = inbound(messages=next(batches), name=name)
        poll += 1
    return batch


def inbound(messages: Iterable[Path], name: str) -> list[Path]:
    return sorted(
        message for message in messages if not is_own_thread_message(message=message, name=name)
    )


def report(
    messages: list[Path],
    policy: InboundPolicy,
    duplicates: DuplicateFilter,
) -> None:
    now = datetime.now().astimezone()
    for message in messages:
        verdict, path = screen_message(
            message=message, policy=policy, duplicates=duplicates, now=now
        )
        print(f"{verdict} {path}", flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Print '<VERDICT> <path>' for each message arriving in a claude-bus mailbox."
    )
    parser.add_argument("name", help="mailbox name to watch (threads included)")
    parser.add_argument(
        "--hold",
        action="append",
        default=[],
        metavar="SENDER",
        help="report this sender's messages as HELD for approval (repeatable)",
    )
    parser.add_argument(
        "--refuse",
        action="append",
        default=[],
        metavar="SENDER",
        help="mark this sender's messages read unseen, reported as REFUSED (repeatable)",
    )
    parser.add_argument("--root", type=Path, default=BUS_ROOT, help=argparse.SUPPRESS)
    parser.add_argument(
        "--interval", type=float, default=POLL_INTERVAL_SECONDS, help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="report unread mail, or wait for the next arrival, then exit 0",
    )
    parser.add_argument(
        "--polls",
        type=int,
        default=None,
        help="with --once, give up after N polls; 0 reports unread mail without waiting",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_mailbox_name(field="mailbox", value=args.name)
        policy = InboundPolicy(refuse=frozenset(args.refuse), hold=frozenset(args.hold))
    except InvalidMessageError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return INVALID_MESSAGE_EXIT
    duplicates = DuplicateFilter()
    if args.once:
        report(
            messages=next_batch(
                root=args.root, name=args.name, interval=args.interval, polls=args.polls
            ),
            policy=policy,
            duplicates=duplicates,
        )
        return 0
    for poll, batch in enumerate(
        arrivals(root=args.root, name=args.name, interval=args.interval), start=1
    ):
        report(messages=batch, policy=policy, duplicates=duplicates)
        if args.polls is not None and poll >= args.polls:
            break
    return 0
