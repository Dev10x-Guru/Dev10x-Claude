"""Tests for the claude-bus status board (GH-1624)."""

from __future__ import annotations

import stat
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from dev10x.skills.bus.maildir import (
    INVALID_MESSAGE_EXIT,
    InvalidMessageError,
    SessionStatus,
    parse_status,
    status_files,
    write_status,
)

from dev10x.skills.bus import board, status
from tests.skills.bus.conftest import Run

RunMain = Callable[[Callable[..., int], list[str]], Run]
NOW = datetime(2026, 10, 18, 12, 0, 0, tzinfo=UTC)


def _status(
    mailbox: str = "dev10x-7",
    state: str = "working",
    summary: str = "Fixing the login redirect.",
    minutes_ago: int = 0,
    callsign: str = "",
) -> SessionStatus:
    return SessionStatus(
        mailbox=mailbox,
        state=state,
        summary=summary,
        updated=NOW - timedelta(minutes=minutes_ago),
        callsign=callsign,
    )


class TestSessionStatus:
    @pytest.mark.parametrize(
        ("overrides", "match"),
        [
            ({"mailbox": "../x"}, "mailbox"),
            ({"state": "sleeping"}, "state"),
            ({"summary": "a\nb"}, "Summary"),
            ({"callsign": "a\nb"}, "Callsign"),
        ],
    )
    def test_rejects(self, overrides: dict[str, str], match: str) -> None:
        with pytest.raises(InvalidMessageError, match=match):
            _status(**overrides)

    @pytest.mark.parametrize(
        ("callsign", "expected"),
        [("", "dev10x-7"), ("login fix", "login fix [dev10x-7]")],
    )
    def test_label(self, callsign: str, expected: str) -> None:
        assert _status(callsign=callsign).label == expected


class TestWriteStatus:
    @pytest.fixture
    def written(self, root: Path) -> Path:
        write_status(root=root, status=_status(state="working"))
        return write_status(root=root, status=_status(state="done", callsign="login fix"))

    def test_one_file_per_mailbox(self, root: Path, written: Path) -> None:
        assert status_files(root=root) == [root / "status" / "dev10x-7"]

    def test_round_trips_the_latest_state(self, written: Path) -> None:
        assert parse_status(path=written) == _status(state="done", callsign="login fix")

    def test_leaves_no_draft(self, root: Path, written: Path) -> None:
        assert sorted(path.name for path in (root / "status").iterdir()) == ["dev10x-7"]

    def test_creates_private_root(self, root: Path, written: Path) -> None:
        assert stat.S_IMODE(root.stat().st_mode) == 0o700


class TestParseStatus:
    @pytest.mark.parametrize(
        "text",
        [
            "no frontmatter",
            "---\nMailbox: a\n---\n\nmissing state",
            "---\nMailbox: a\nState: lost\nUpdated: 2026-10-18T12:00:00+00:00\n---\n\nx",
            "---\nMailbox: a\nState: done\nUpdated: yesterday\n---\n\nx",
        ],
    )
    def test_malformed_is_none(self, tmp_path: Path, text: str) -> None:
        path = tmp_path / "s"
        path.write_text(text, encoding="utf-8")

        assert parse_status(path=path) is None


class TestStatusFiles:
    def test_missing_directory_is_empty(self, root: Path) -> None:
        assert status_files(root=root) == []

    def test_skips_hidden_drafts_and_directories(self, root: Path) -> None:
        directory = root / "status"
        (directory / "nested").mkdir(parents=True)
        (directory / ".a.tmp").touch()
        (directory / "a").touch()

        assert status_files(root=root) == [directory / "a"]


@pytest.mark.parametrize(
    ("elapsed", "expected"),
    [
        (timedelta(seconds=20), "just now"),
        (timedelta(minutes=5), "5 min ago"),
        (timedelta(hours=3, minutes=10), "3 h ago"),
        (timedelta(days=2, hours=1), "2 d ago"),
    ],
)
def test_describe_age(elapsed: timedelta, expected: str) -> None:
    assert board.describe_age(elapsed=elapsed) == expected


class TestRenderBoard:
    def test_empty_board(self) -> None:
        assert board.render_board(statuses=[], now=NOW) == board.EMPTY_BOARD

    def test_groups_needs_you_first_and_newest_first(self) -> None:
        statuses = [
            _status(mailbox="a", state="done", summary="Shipped the docs.", minutes_ago=90),
            _status(mailbox="b", state="working", summary="Running tests.", minutes_ago=2),
            _status(
                mailbox="c",
                state="needs-input",
                summary="Keep the old endpoint?",
                minutes_ago=5,
                callsign="payments",
            ),
            _status(mailbox="d", state="working", summary="Reading code.", minutes_ago=1),
        ]

        assert board.render_board(statuses=statuses, now=NOW) == (
            "Needs you (1)\n"
            "  payments [c] — Keep the old endpoint? (5 min ago)\n"
            "Working (2)\n"
            "  d — Reading code. (1 min ago)\n"
            "  b — Running tests. (2 min ago)\n"
            "Done (1)\n"
            "  a — Shipped the docs. (1 h ago)"
        )


class TestStatusMain:
    @pytest.fixture
    def run(self, root: Path, run_main: RunMain) -> Run:
        return run_main(
            status.main,
            [
                "dev10x-7",
                "needs-input",
                "Keep the old endpoint?",
                "--callsign",
                "payments",
                "--notify",
                "cowork",
                "--root",
                str(root),
            ],
        )

    def test_exits_zero(self, run: Run) -> None:
        assert run.exit_code == 0

    def test_reports_status_then_notice(self, run: Run) -> None:
        assert [line.split(" ")[0] for line in run.stdout.splitlines()] == ["STATUS", "SENT"]

    def test_notice_names_callsign_and_state(self, run: Run, root: Path) -> None:
        (notice,) = (root / "cowork" / "new").iterdir()

        assert "Subject: payments: needs-input\n" in notice.read_text(encoding="utf-8")

    @pytest.fixture
    def rejected(self, root: Path, run_main: RunMain) -> Run:
        return run_main(status.main, ["dev10x-7", "done", "line\nbreak", "--root", str(root)])

    def test_invalid_status_exits_two(self, rejected: Run) -> None:
        assert rejected.exit_code == INVALID_MESSAGE_EXIT

    def test_invalid_status_writes_nothing(self, rejected: Run, root: Path) -> None:
        assert status_files(root=root) == []

    def test_invalid_notify_writes_nothing(self, root: Path, run_main: RunMain) -> None:
        result = run_main(
            status.main, ["dev10x-7", "done", "ok", "--notify", "../x", "--root", str(root)]
        )

        assert (result.exit_code, status_files(root=root)) == (INVALID_MESSAGE_EXIT, [])


class TestBoardMain:
    @pytest.fixture
    def run(self, root: Path, run_main: RunMain) -> Run:
        write_status(root=root, status=_status(state="needs-input", summary="Pick one."))
        (root / "status" / "junk").write_text("noise", encoding="utf-8")
        return run_main(board.main, ["--root", str(root)])

    def test_exits_zero(self, run: Run) -> None:
        assert run.exit_code == 0

    def test_prints_the_board(self, run: Run) -> None:
        assert run.stdout.startswith("Needs you (1)\n  dev10x-7 — Pick one. (")

    def test_reports_unreadable_files(self, run: Run, root: Path) -> None:
        assert run.stderr == f"SKIP {root / 'status' / 'junk'} (not a status file)\n"
