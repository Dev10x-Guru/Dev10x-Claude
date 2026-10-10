"""Tests for the claude-bus send / watch / done entry points (GH-1516)."""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

import pytest

from dev10x.skills.bus import done, send, watch
from dev10x.skills.bus.maildir import INVALID_MESSAGE_EXIT
from tests.skills.bus.conftest import Run

RunMain = Callable[[Callable[..., int], list[str]], Run]


def _only_message(mailbox: Path) -> str:
    (message,) = (mailbox / "new").iterdir()
    return message.read_text(encoding="utf-8")


class TestSendMain:
    @pytest.fixture
    def body_file(self, tmp_path: Path) -> Path:
        path = tmp_path / "body.txt"
        path.write_text("hello there\n", encoding="utf-8")
        return path

    @pytest.fixture
    def run(self, root: Path, body_file: Path, run_main: RunMain) -> Run:
        return run_main(
            send.main,
            [
                "registry",
                "hello",
                str(body_file),
                "--from",
                "dev10x-7",
                "--header",
                "Role=dev10x",
                "--voice",
                "--root",
                str(root),
            ],
        )

    @pytest.fixture
    def delivered(self, run: Run, root: Path) -> str:
        return _only_message(mailbox=root / "registry")

    @pytest.fixture
    def stdin_delivered(
        self,
        root: Path,
        monkeypatch: pytest.MonkeyPatch,
        run_main: RunMain,
    ) -> str:
        monkeypatch.setattr("sys.stdin", io.StringIO("from stdin"))
        run_main(send.main, ["a", "s", "-", "--from", "b", "--root", str(root)])
        return _only_message(mailbox=root / "a")

    def test_exits_zero(self, run: Run) -> None:
        assert run.exit_code == 0

    def test_prints_sent_path_then_message_id(self, run: Run) -> None:
        assert [line.split(" ")[0] for line in run.stdout.splitlines()] == [
            "SENT",
            "Message-ID:",
        ]

    @pytest.mark.parametrize("fragment", ["Role: dev10x\n", "Voice: yes\n"])
    def test_writes_header(self, delivered: str, fragment: str) -> None:
        assert fragment in delivered

    def test_writes_body_last(self, delivered: str) -> None:
        assert delivered.endswith("hello there\n")

    def test_reads_body_from_stdin(self, stdin_delivered: str) -> None:
        assert stdin_delivered.endswith("from stdin\n")

    @pytest.fixture
    def rejected(self, root: Path, body_file: Path, run_main: RunMain) -> Run:
        return run_main(
            send.main, ["../escape", "s", str(body_file), "--from", "b", "--root", str(root)]
        )

    def test_invalid_message_exits_two(self, rejected: Run) -> None:
        assert rejected.exit_code == INVALID_MESSAGE_EXIT

    def test_header_without_equals_is_a_usage_error(self, root: Path, body_file: Path) -> None:
        with pytest.raises(SystemExit) as exited:
            send.main(
                argv=[
                    "a",
                    "s",
                    str(body_file),
                    "--from",
                    "b",
                    "--header",
                    "Role",
                    "--root",
                    str(root),
                ]
            )

        assert exited.value.code == 2

    def test_invalid_message_names_the_field(self, rejected: Run) -> None:
        assert rejected.stderr.startswith("ERROR recipient '../escape'")


class TestWatchMain:
    @pytest.fixture
    def inbox(self, root: Path) -> Path:
        path = root / "a" / "new"
        path.mkdir(parents=True)
        (path / "old").touch()
        return path

    @pytest.fixture
    def run(
        self,
        root: Path,
        inbox: Path,
        monkeypatch: pytest.MonkeyPatch,
        run_main: RunMain,
    ) -> Run:
        monkeypatch.setattr(watch.time, "sleep", lambda seconds: (inbox / "fresh").touch())
        return run_main(watch.main, ["a", "--root", str(root), "--polls", "2"])

    def test_exits_after_requested_polls(self, run: Run) -> None:
        assert run.exit_code == 0

    def test_reports_only_arrivals(self, run: Run, inbox: Path) -> None:
        assert run.stdout == f"NEW {inbox / 'fresh'}\n"

    @pytest.fixture
    def rejected(self, root: Path, run_main: RunMain) -> Run:
        return run_main(watch.main, ["../x", "--root", str(root), "--polls", "1"])

    def test_invalid_name_exits_two(self, rejected: Run) -> None:
        assert rejected.exit_code == INVALID_MESSAGE_EXIT

    def test_invalid_name_is_reported(self, rejected: Run) -> None:
        assert rejected.stderr.startswith("ERROR mailbox '../x'")

    def test_arrivals_follows_threads(self, root: Path) -> None:
        thread_new = root / "threads" / "a--b" / "new"
        thread_new.mkdir(parents=True)

        batches = watch.arrivals(
            root=root,
            name="a",
            interval=0.0,
            sleep=lambda seconds: (thread_new / "m").touch(),
        )

        assert next(batches) == [thread_new / "m"]


class TestDoneMain:
    @pytest.fixture
    def message(self, root: Path) -> Path:
        inbox = root / "a" / "new"
        inbox.mkdir(parents=True)
        path = inbox / "m1"
        path.touch()
        return path

    @pytest.fixture
    def mailbox_run(self, root: Path, message: Path, run_main: RunMain) -> Run:
        return run_main(done.main, ["a", "--root", str(root)])

    @pytest.fixture
    def stray(self, root: Path) -> Path:
        return root / "a" / "cur" / "x"

    @pytest.fixture
    def mixed_run(self, root: Path, message: Path, stray: Path, run_main: RunMain) -> Run:
        return run_main(done.main, [str(message), str(stray), "--root", str(root)])

    def test_mailbox_exits_zero(self, mailbox_run: Run) -> None:
        assert mailbox_run.exit_code == 0

    def test_mailbox_reports_cur_path(self, mailbox_run: Run, root: Path) -> None:
        assert mailbox_run.stdout == f"CUR {root / 'a' / 'cur' / 'm1:2,S'}\n"

    def test_skip_fails_the_run(self, mixed_run: Run) -> None:
        assert mixed_run.exit_code == done.SKIPPED_EXIT

    def test_skip_is_reported(self, mixed_run: Run, stray: Path) -> None:
        assert f"SKIP {stray}" in mixed_run.stderr

    def test_skip_still_marks_the_rest(self, mixed_run: Run, root: Path) -> None:
        assert (root / "a" / "cur" / "m1:2,S").is_file()

    @pytest.fixture
    def missing_run(self, root: Path, run_main: RunMain) -> Run:
        return run_main(done.main, ["nobody", "--root", str(root)])

    def test_missing_mailbox_fails(self, missing_run: Run) -> None:
        assert missing_run.exit_code == INVALID_MESSAGE_EXIT

    def test_missing_mailbox_is_reported(self, missing_run: Run) -> None:
        assert missing_run.stderr.startswith("ERROR mailbox 'nobody'")
