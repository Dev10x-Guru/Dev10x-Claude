from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dev10x.comm.skills.bus.maildir import (
    BUS_ROOT,
    SessionStatus,
    parse_status,
    status_files,
)

GROUPS = (("needs-input", "Needs you"), ("working", "Working"), ("done", "Done"))
EMPTY_BOARD = "No session has published a status yet."


def describe_age(elapsed: timedelta) -> str:
    minutes = int(elapsed.total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    if minutes < 24 * 60:
        return f"{minutes // 60} h ago"
    return f"{minutes // (24 * 60)} d ago"


def render_board(statuses: list[SessionStatus], now: datetime) -> str:
    lines: list[str] = []
    for state, title in GROUPS:
        group = sorted(
            (status for status in statuses if status.state == state),
            key=lambda status: status.updated,
            reverse=True,
        )
        if not group:
            continue
        lines.append(f"{title} ({len(group)})")
        lines.extend(
            f"  {status.label} — {status.summary} ({describe_age(elapsed=now - status.updated)})"
            for status in group
        )
    return "\n".join(lines) or EMPTY_BOARD


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Print the claude-bus status board: who needs you, who works, who is done."
    )
    parser.add_argument("--root", type=Path, default=BUS_ROOT, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    statuses: list[SessionStatus] = []
    for path in status_files(root=args.root):
        status = parse_status(path=path)
        if status is None:
            print(f"SKIP {path} (not a status file)", file=sys.stderr)
            continue
        statuses.append(status)
    print(render_board(statuses=statuses, now=datetime.now().astimezone()))
    return 0
