"""Tests for the claude-bus send / watch / done entry points (GH-1516)."""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

import pytest
from dev10x.skills.bus.maildir import INVALID_MESSAGE_EXIT

from dev10x.skills.bus import done, maildir, send, watch
from tests.skills.bus.conftest import Run

RunMain = Callable[[Callable[..., int], list[str]], Run]
SCREENED_ARRIVALS = {
    "a-loop-1": "---\nFrom: looper\nSubject: ping\n---\n\nsame\n",
    "a-loop-2": "---\nFrom: looper\nSubject: ping\n---\n\nsame\n",
    "b-held": "---\nFrom: stranger\nSubject: hi\n---\n\nhello\n",
    "c-refused": "---\nFrom: spammer\nSubject: buy\n---\n\nnow\n",
    "d-expired": (
        "---\nFrom: cowork\nSubject: old\nExpires: 2000-01-01T00:00:00+00:00\n---\n\nstale\n"
    ),
}


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

    def test_expires_in_writes_expires_header(
        self, root: Path, body_file: Path, run_main: RunMain
    ) -> None:
        run_main(
            send.main,
            ["a", "s", str(body_file), "--from", "b", "--expires-in", "15", "--root", str(root)],
        )

        assert "\nExpires: " in _only_message(mailbox=root / "a")

    @pytest.mark.parametrize("raw", ["soon", "0"])
    def test_expires_in_rejects_bad_minutes(self, root: Path, body_file: Path, raw: str) -> None:
        with pytest.raises(SystemExit) as exited:
            send.main(argv=["a", "s", str(body_file), "--from", "b", "--expires-in", raw])

        assert exited.value.code == 2


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

    @pytest.fixture
    def screened_run(
        self,
        root: Path,
        inbox: Path,
        monkeypatch: pytest.MonkeyPatch,
        run_main: RunMain,
    ) -> Run:
        def deliver(seconds: float) -> None:
            for name, text in SCREENED_ARRIVALS.items():
                (inbox / name).write_text(text, encoding="utf-8")

        monkeypatch.setattr(watch.time, "sleep", deliver)
        return run_main(
            watch.main,
            [
                "a",
                "--hold",
                "stranger",
                "--refuse",
                "spammer",
                "--root",
                str(root),
                "--polls",
                "1",
            ],
        )

    def test_screens_each_arrival(self, screened_run: Run, root: Path, inbox: Path) -> None:
        cur = root / "a" / "cur"

        assert screened_run.stdout.splitlines() == [
            f"NEW {inbox / 'a-loop-1'}",
            f"DUP {cur / 'a-loop-2:2,S'}",
            f"HELD {inbox / 'b-held'}",
            f"REFUSED {cur / 'c-refused:2,S'}",
            f"EXPIRED {cur / 'd-expired:2,S'}",
        ]

    def test_invalid_policy_sender_exits_two(self, root: Path, run_main: RunMain) -> None:
        result = run_main(watch.main, ["a", "--hold", "../x", "--root", str(root)])

        assert result.exit_code == INVALID_MESSAGE_EXIT

    @pytest.fixture
    def sleeps(
        self,
        root: Path,
        inbox: Path,
        monkeypatch: pytest.MonkeyPatch,
        run_main: RunMain,
    ) -> list[float]:
        calls: list[float] = []
        monkeypatch.setattr(watch.time, "sleep", calls.append)
        run_main(watch.main, ["a", "--root", str(root), "--polls", "3"])
        return calls

    def test_keeps_polling_after_a_quiet_poll(self, sleeps: list[float]) -> None:
        assert len(sleeps) == 3


class TestWatchOnceMain:
    @pytest.fixture
    def inbox(self, root: Path) -> Path:
        path = root / "a" / "new"
        path.mkdir(parents=True)
        return path

    @pytest.fixture
    def unread_run(
        self,
        root: Path,
        inbox: Path,
        monkeypatch: pytest.MonkeyPatch,
        run_main: RunMain,
    ) -> Run:
        (inbox / "old").touch()
        thread_new = root / "threads" / "a--b" / "new"
        thread_new.mkdir(parents=True)
        (thread_new / "aside").touch()

        def refuse_to_wait(seconds: float) -> None:
            raise AssertionError("--once waited despite unread mail")

        monkeypatch.setattr(watch.time, "sleep", refuse_to_wait)
        return run_main(watch.main, ["a", "--once", "--root", str(root)])

    def test_unread_mail_exits_zero(self, unread_run: Run) -> None:
        assert unread_run.exit_code == 0

    def test_reports_unread_mail_without_waiting(
        self, unread_run: Run, root: Path, inbox: Path
    ) -> None:
        assert unread_run.stdout == (
            f"NEW {inbox / 'old'}\nNEW {root / 'threads' / 'a--b' / 'new' / 'aside'}\n"
        )

    @pytest.fixture
    def arrival_run(
        self,
        root: Path,
        inbox: Path,
        monkeypatch: pytest.MonkeyPatch,
        run_main: RunMain,
    ) -> Run:
        polls = iter([lambda: None, (inbox / "fresh").touch])
        monkeypatch.setattr(watch.time, "sleep", lambda seconds: next(polls)())
        return run_main(watch.main, ["a", "--once", "--root", str(root)])

    def test_arrival_exits_zero(self, arrival_run: Run) -> None:
        assert arrival_run.exit_code == 0

    def test_waits_through_quiet_polls_for_the_arrival(
        self, arrival_run: Run, inbox: Path
    ) -> None:
        assert arrival_run.stdout == f"NEW {inbox / 'fresh'}\n"

    @pytest.fixture
    def quiet_run(
        self,
        root: Path,
        inbox: Path,
        monkeypatch: pytest.MonkeyPatch,
        run_main: RunMain,
    ) -> Run:
        monkeypatch.setattr(watch.time, "sleep", lambda seconds: None)
        return run_main(watch.main, ["a", "--once", "--root", str(root), "--polls", "2"])

    def test_polls_bound_a_quiet_wait(self, quiet_run: Run) -> None:
        assert (quiet_run.exit_code, quiet_run.stdout) == (0, "")

    @pytest.fixture
    def check_only_run(
        self,
        root: Path,
        inbox: Path,
        monkeypatch: pytest.MonkeyPatch,
        run_main: RunMain,
    ) -> Run:
        def refuse_to_wait(seconds: float) -> None:
            raise AssertionError("--polls 0 waited")

        monkeypatch.setattr(watch.time, "sleep", refuse_to_wait)
        return run_main(watch.main, ["a", "--once", "--root", str(root), "--polls", "0"])

    def test_zero_polls_checks_without_waiting(self, check_only_run: Run) -> None:
        assert (check_only_run.exit_code, check_only_run.stdout) == (0, "")

    @pytest.fixture
    def own_thread_run(
        self,
        root: Path,
        inbox: Path,
        monkeypatch: pytest.MonkeyPatch,
        run_main: RunMain,
    ) -> Run:
        maildir.send(
            root=root,
            envelope=maildir.Envelope(sender="a", recipient="b", subject="to b"),
            body="x",
            thread=True,
        )
        monkeypatch.setattr(watch.time, "sleep", lambda seconds: (inbox / "fresh").touch())
        return run_main(watch.main, ["a", "--once", "--root", str(root)])

    def test_waits_past_own_outgoing_thread_mail(self, own_thread_run: Run, inbox: Path) -> None:
        assert own_thread_run.stdout == f"NEW {inbox / 'fresh'}\n"

    @pytest.fixture
    def read_by_peer_run(
        self,
        root: Path,
        inbox: Path,
        monkeypatch: pytest.MonkeyPatch,
        run_main: RunMain,
    ) -> Run:
        outgoing = maildir.send(
            root=root,
            envelope=maildir.Envelope(sender="a", recipient="b", subject="to b"),
            body="x",
            thread=True,
        )
        polls = iter([lambda: maildir.mark_read(message=outgoing.path), (inbox / "fresh").touch])
        monkeypatch.setattr(watch.time, "sleep", lambda seconds: next(polls)())
        return run_main(watch.main, ["a", "--once", "--root", str(root)])

    def test_mail_read_elsewhere_does_not_end_the_wait(
        self, read_by_peer_run: Run, inbox: Path
    ) -> None:
        assert read_by_peer_run.stdout == f"NEW {inbox / 'fresh'}\n"

    @pytest.fixture
    def snapshot_window_run(
        self,
        root: Path,
        inbox: Path,
        monkeypatch: pytest.MonkeyPatch,
        run_main: RunMain,
    ) -> Run:
        real_unread = watch.unread
        after_first_check = iter([(inbox / "fresh").touch])

        def unread_then_arrive(maildirs: list[Path]) -> set[Path]:
            snapshot = real_unread(maildirs=maildirs)
            next(after_first_check, lambda: None)()
            return snapshot

        monkeypatch.setattr(watch, "unread", unread_then_arrive)
        monkeypatch.setattr(watch.time, "sleep", lambda seconds: None)
        return run_main(watch.main, ["a", "--once", "--root", str(root), "--polls", "2"])

    def test_reports_mail_landing_right_after_the_unread_check(
        self, snapshot_window_run: Run, inbox: Path
    ) -> None:
        assert snapshot_window_run.stdout == f"NEW {inbox / 'fresh'}\n"

    @pytest.fixture
    def screened_once_run(
        self,
        root: Path,
        inbox: Path,
        monkeypatch: pytest.MonkeyPatch,
        run_main: RunMain,
    ) -> Run:
        for name, text in SCREENED_ARRIVALS.items():
            (inbox / name).write_text(text, encoding="utf-8")
        monkeypatch.setattr(watch.time, "sleep", lambda seconds: None)
        return run_main(
            watch.main,
            ["a", "--once", "--refuse", "spammer", "--root", str(root), "--polls", "0"],
        )

    def test_once_screens_unread_mail(
        self, screened_once_run: Run, root: Path, inbox: Path
    ) -> None:
        cur = root / "a" / "cur"

        assert screened_once_run.stdout.splitlines() == [
            f"NEW {inbox / 'a-loop-1'}",
            f"DUP {cur / 'a-loop-2:2,S'}",
            f"NEW {inbox / 'b-held'}",
            f"REFUSED {cur / 'c-refused:2,S'}",
            f"EXPIRED {cur / 'd-expired:2,S'}",
        ]


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
