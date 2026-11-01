"""Tests for the dev supervisor page launcher (GH-1765)."""

from __future__ import annotations

import signal
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from dev10x.comm.supervisor import dev_launcher
from dev10x.comm.supervisor.dev_checkout import DevCheckout
from dev10x.comm.supervisor.dev_launcher import DevLauncher

CHECKOUT = Path("/w/dx")


class FakeChild:
    def __init__(self, *, pid: int, exit_code: int | None = None, hangs: bool = False) -> None:
        self.pid = pid
        self.returncode = exit_code
        self.hangs = hangs
        self.waits: list[float | None] = []

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        self.waits.append(timeout)
        if self.hangs and timeout is not None:
            raise subprocess.TimeoutExpired(cmd="uv", timeout=timeout)
        self.returncode = -15 if self.returncode is None else self.returncode
        return self.returncode


class Recorder:
    def __init__(self, *, children: list[FakeChild | OSError]) -> None:
        self.children = iter(children)
        self.spawned: list[tuple[list[str], dict[str, Any]]] = []
        self.signals: list[tuple[int, int]] = []
        self.lines: list[str] = []

    def spawn(self, command: list[str], **kwargs: Any) -> FakeChild:
        self.spawned.append((command, kwargs))
        child = next(self.children)
        if isinstance(child, OSError):
            raise child
        return child

    def kill(self, pid: int, signum: int) -> None:
        self.signals.append((pid, signum))


def _heads(*, values: list[str | None], stop: threading.Event) -> Iterator[str | None]:
    yield from values
    stop.set()
    while True:
        yield values[-1]


def _launch(
    *,
    recorder: Recorder,
    heads: list[str | None],
) -> DevLauncher:
    stop = threading.Event()
    sequence = _heads(values=heads, stop=stop)
    launcher = DevLauncher(
        command=["uv", "run"],
        checkout=CHECKOUT,
        announce=recorder.lines.append,
        spawner=recorder.spawn,  # type: ignore[arg-type]
        head_reader=lambda *, checkout: next(sequence),
        killer=recorder.kill,
    )
    launcher.run(stop=stop, interval=0)
    return launcher


class TestRun:
    def test_starts_the_child_in_its_own_session(self) -> None:
        recorder = Recorder(children=[FakeChild(pid=10)])

        _launch(recorder=recorder, heads=["a", "a"])

        assert recorder.spawned == [(["uv", "run"], {"cwd": "/w/dx", "start_new_session": True})]

    def test_restarts_when_head_moves(self) -> None:
        recorder = Recorder(children=[FakeChild(pid=10), FakeChild(pid=11)])

        _launch(recorder=recorder, heads=["a", "b"])

        assert (len(recorder.spawned), recorder.signals, recorder.lines[1]) == (
            2,
            [(10, signal.SIGTERM), (11, signal.SIGTERM)],
            "Checkout moved to b; restarting the dev page",
        )

    def test_unreadable_head_does_not_restart(self) -> None:
        recorder = Recorder(children=[FakeChild(pid=10)])

        _launch(recorder=recorder, heads=[None, None])

        assert (len(recorder.spawned), recorder.lines[0]) == (
            1,
            "Dev supervisor page from /w/dx at unknown HEAD",
        )

    def test_first_readable_head_becomes_the_baseline(self) -> None:
        recorder = Recorder(children=[FakeChild(pid=10)])

        _launch(recorder=recorder, heads=[None, "a"])

        assert (len(recorder.spawned), recorder.signals) == (1, [(10, signal.SIGTERM)])

    def test_announces_a_lost_head_once(self) -> None:
        recorder = Recorder(children=[FakeChild(pid=10)])

        _launch(recorder=recorder, heads=["a", None, None])

        assert recorder.lines[1:] == [
            "Cannot read HEAD of /w/dx (`git rev-parse HEAD` failed); the dev page stays on a"
        ]

    def test_announces_when_head_is_readable_again(self) -> None:
        recorder = Recorder(children=[FakeChild(pid=10)])

        _launch(recorder=recorder, heads=[None, "a"])

        assert recorder.lines[1] == "HEAD of /w/dx is readable again at a"

    def test_survives_a_failed_spawn_and_retries(self) -> None:
        recorder = Recorder(children=[OSError("uv: not found"), FakeChild(pid=11)])

        _launch(recorder=recorder, heads=["a", "a"])

        assert (recorder.lines[1], recorder.signals) == (
            "Cannot start the dev page: uv: not found; retrying",
            [(11, signal.SIGTERM)],
        )

    def test_restarts_a_crashed_child(self) -> None:
        recorder = Recorder(children=[FakeChild(pid=10, exit_code=1), FakeChild(pid=11)])

        _launch(recorder=recorder, heads=["a", "a"])

        assert (len(recorder.spawned), recorder.lines[1]) == (
            2,
            "Dev page exited with 1 (1 in a row); restarting in 0s",
        )

    def test_backs_off_a_crash_loop(self) -> None:
        recorder = Recorder(
            children=[
                FakeChild(pid=10, exit_code=1),
                FakeChild(pid=11, exit_code=1),
                FakeChild(pid=12, exit_code=1),
                FakeChild(pid=13),
            ]
        )

        _launch(recorder=recorder, heads=["a"] * 8)

        assert (len(recorder.spawned), recorder.lines[-1]) == (
            3,
            "Dev page exited with 1 (3 in a row); restarting in 0s",
        )

    def test_backs_off_a_spawn_that_keeps_failing(self) -> None:
        recorder = Recorder(children=[OSError("no uv")] * 4 + [FakeChild(pid=13)])

        _launch(recorder=recorder, heads=["a"] * 5)

        assert len(recorder.spawned) == 4

    def test_kills_a_child_that_ignores_sigterm(self) -> None:
        stubborn = FakeChild(pid=10, hangs=True)
        recorder = Recorder(children=[stubborn])

        _launch(recorder=recorder, heads=["a", "a"])

        assert (recorder.signals, stubborn.waits) == (
            [(10, signal.SIGTERM), (10, signal.SIGKILL)],
            [dev_launcher.STOP_TIMEOUT_SECONDS, None],
        )

    def test_a_gone_process_group_is_not_an_error(self) -> None:
        recorder = Recorder(children=[FakeChild(pid=10)])

        def gone(pid: int, signum: int) -> None:
            raise ProcessLookupError(pid)

        recorder.kill = gone  # type: ignore[method-assign]

        _launch(recorder=recorder, heads=["a", "a"])

        assert len(recorder.spawned) == 1


def test_an_exited_child_is_not_signalled_on_shutdown() -> None:
    recorder = Recorder(children=[FakeChild(pid=10, exit_code=0)])
    stop = threading.Event()
    stop.set()
    launcher = DevLauncher(
        command=["uv", "run"],
        checkout=CHECKOUT,
        announce=recorder.lines.append,
        spawner=recorder.spawn,  # type: ignore[arg-type]
        head_reader=lambda *, checkout: "a",
        killer=recorder.kill,
    )

    launcher.run(stop=stop, interval=0)

    assert (len(recorder.spawned), recorder.signals) == (1, [])


@pytest.mark.parametrize(
    ("failures", "ticks"),
    [(0, 0), (1, 0), (2, 1), (3, 3), (4, 7), (5, 11), (20, 11)],
)
def test_backoff_doubles_up_to_the_cap(failures: int, ticks: int) -> None:
    assert dev_launcher.backoff_ticks(failures=failures) == ticks


class TestReadHead:
    @pytest.mark.parametrize(
        ("returncode", "stdout", "expected"),
        [(0, "abc\n", "abc"), (128, "", None), (0, "  \n", None)],
        ids=["ok", "not-a-repo", "blank"],
    )
    def test_parses_rev_parse(self, returncode: int, stdout: str, expected: str | None) -> None:
        calls: list[dict[str, Any]] = []

        def runner(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            calls.append({"args": args, **kwargs})
            return subprocess.CompletedProcess(args=args, returncode=returncode, stdout=stdout)

        head = dev_launcher.read_head(checkout=CHECKOUT, runner=runner)

        assert (head, calls[0]["args"], calls[0]["cwd"], calls[0]["timeout"]) == (
            expected,
            ["git", "rev-parse", "HEAD"],
            "/w/dx",
            dev_launcher.HEAD_TIMEOUT_SECONDS,
        )

    @pytest.mark.parametrize(
        "error",
        [OSError("no git"), subprocess.TimeoutExpired(cmd="git", timeout=1)],
        ids=["os-error", "timeout"],
    )
    def test_failure_is_unknown(self, error: Exception) -> None:
        def runner(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            raise error

        assert dev_launcher.read_head(checkout=CHECKOUT, runner=runner) is None


def test_child_command_runs_the_checkout_code(tmp_path: Path) -> None:
    command = dev_launcher.child_command(
        dev=DevCheckout(checkout=CHECKOUT, port=9300),
        uv="/bin/uv",
        interval=2.0,
        kb_root=tmp_path / "kb",
        bus_root=tmp_path / "bus",
        relay_mailbox="relay",
    )

    assert command == [
        "/bin/uv",
        "run",
        "--project",
        "/w/dx",
        "dev10x",
        "supervisor",
        "serve",
        "--instance",
        "dev",
        "--port",
        "9300",
        "--interval",
        "2.0",
        "--kb-root",
        str(tmp_path / "kb"),
        "--bus-root",
        str(tmp_path / "bus"),
        "--relay-mailbox",
        "relay",
    ]
