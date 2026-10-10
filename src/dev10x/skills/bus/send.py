from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dev10x.skills.bus.maildir import (
    BUS_ROOT,
    INVALID_MESSAGE_EXIT,
    Envelope,
    InvalidMessageError,
    send,
)


def parse_header(raw: str) -> tuple[str, str]:
    key, separator, value = raw.partition("=")
    if not separator:
        raise argparse.ArgumentTypeError(f"{raw!r} is not KEY=VALUE")
    return key, value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deliver a claude-bus message (Maildir, RFC 5322 headers)."
    )
    parser.add_argument("recipient", help="mailbox name, e.g. cowork, dev10x-7, registry")
    parser.add_argument("subject")
    parser.add_argument("body_file", help="file with the body, or - for stdin")
    parser.add_argument("--from", dest="sender", required=True)
    parser.add_argument("--reply-to", dest="reply_to")
    parser.add_argument("--in-reply-to", dest="in_reply_to")
    parser.add_argument("--references")
    parser.add_argument(
        "--voice",
        action="store_true",
        help="answer will be read aloud (<=3 plain sentences)",
    )
    parser.add_argument(
        "--thread",
        action="store_true",
        help="deliver to threads/<a>--<b>/ instead of the recipient inbox",
    )
    parser.add_argument(
        "--header", action="append", default=[], type=parse_header, metavar="KEY=VALUE"
    )
    parser.add_argument("--root", type=Path, default=BUS_ROOT, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    body = (
        sys.stdin.read()
        if args.body_file == "-"
        else Path(args.body_file).read_text(encoding="utf-8")
    )
    try:
        delivery = send(
            root=args.root,
            envelope=Envelope(
                sender=args.sender,
                recipient=args.recipient,
                subject=args.subject,
                reply_to=args.reply_to,
                in_reply_to=args.in_reply_to,
                references=args.references,
                voice=args.voice,
                extra_headers=tuple(args.header),
            ),
            body=body,
            thread=args.thread,
        )
    except InvalidMessageError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return INVALID_MESSAGE_EXIT
    print(f"SENT {delivery.path}\nMessage-ID: {delivery.message_id}")
    return 0
