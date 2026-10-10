from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dev10x.skills.bus.maildir import (
    BUS_ROOT,
    INVALID_MESSAGE_EXIT,
    InvalidMessageError,
    done_targets,
    is_unread_message,
    mark_read,
)

SKIPPED_EXIT = 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Mark claude-bus messages read (move new/ -> cur/ with the seen flag)."
    )
    parser.add_argument(
        "targets",
        nargs="+",
        help="a mailbox name (marks all of its new/) or message paths in new/",
    )
    parser.add_argument("--root", type=Path, default=BUS_ROOT, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        targets = done_targets(root=args.root, args=args.targets)
    except InvalidMessageError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return INVALID_MESSAGE_EXIT
    skipped = False
    for message in targets:
        if not is_unread_message(message=message):
            print(f"SKIP {message} (not a message in new/)", file=sys.stderr)
            skipped = True
            continue
        print(f"CUR {mark_read(message=message)}")
    return SKIPPED_EXIT if skipped else 0
