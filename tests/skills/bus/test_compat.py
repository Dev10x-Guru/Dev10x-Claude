"""Wire compatibility with the pre-plugin ~/.claude/tools/claude-bus-*.py scripts (GH-1516)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from dev10x.skills.bus.maildir import Delivery, Envelope, headers_for, render, send

LEGACY_HELLO = (
    "---\n"
    "From: dev10x-claude-7-06\n"
    "To: registry\n"
    "Date: 2026-10-10T10:50:22+02:00\n"
    "Subject: hello\n"
    "Message-ID: <20261010T105022.750be9.dev10x-claude-7-06@hagrid>\n"
    "Reply-To: dev10x-claude-7-06\n"
    "Role: dev10x\n"
    "---\n"
    "\n"
    "Dev10x plugin session in /work/dx/.worktrees/Dev10x-Claude-7; "
    "listens on mailbox dev10x-claude-7-06.\n"
)
LEGACY_FILE_NAME = re.compile(r"\d{8}T\d{6}\.\d+\.dev10x-7\.re-hello")
LEGACY_MESSAGE_ID = re.compile(r"<\d{8}T\d{6}\.[0-9a-f]{6}\.dev10x-7@[^>]+>")


@pytest.fixture
def delivery(root: Path) -> Delivery:
    return send(
        root=root,
        envelope=Envelope(sender="dev10x-7", recipient="cowork", subject="Re: hello"),
        body="ok",
    )


def test_renders_byte_identical_to_legacy_hello() -> None:
    rendered = render(
        headers=headers_for(
            envelope=Envelope(
                sender="dev10x-claude-7-06",
                recipient="registry",
                subject="hello",
                reply_to="dev10x-claude-7-06",
                extra_headers=(("Role", "dev10x"),),
            ),
            message_id="<20261010T105022.750be9.dev10x-claude-7-06@hagrid>",
            sent_at=datetime(2026, 10, 10, 10, 50, 22, tzinfo=timezone(timedelta(hours=2))),
        ),
        body=(
            "Dev10x plugin session in /work/dx/.worktrees/Dev10x-Claude-7; "
            "listens on mailbox dev10x-claude-7-06.\n"
        ),
    )

    assert rendered == LEGACY_HELLO


def test_file_name_follows_legacy_shape(delivery: Delivery) -> None:
    assert LEGACY_FILE_NAME.fullmatch(delivery.path.name)


def test_message_id_follows_legacy_shape(delivery: Delivery) -> None:
    assert LEGACY_MESSAGE_ID.fullmatch(delivery.message_id)
