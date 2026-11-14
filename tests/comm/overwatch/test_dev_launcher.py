"""Tests for the dev Overwatch page launcher (GH-1765)."""

from __future__ import annotations

import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from dev10x.comm.overwatch import dev_launcher
from dev10x.comm.overwatch.dev_checkout import DevCheckout
from dev10x.comm.overwatch.dev_launcher import DevLauncher

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


TICK_SECONDS = 5.0


def _heads(*, values: list[str | None], stop: threading.Event) -> Iterator[str | None]:
    yield from values
    stop.set()
    while True:
        yield values[-1]


class TickClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _launch(
    *,
    recorder: Recorder,
    heads: list[str | None],
) -> DevLauncher:
    stop = threading.Event()
    sequence = _heads(values=heads, stop=stop)
    clock = TickClock()

    def read_head(*, checkout: Path) -> str | None:
        clock.now += TICK_SECONDS
        return next(sequence)

    launcher = DevLauncher(
        command=["uv", "run"],
        checkout=CHECKOUT,
        announce=recorder.lines.append,
        spawner=recorder.spawn,  # type: ignore[arg-type]
        head_reader=read_head,
        killer=recorder.kill,
        clock=clock,
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
            "Dev Overwatch page from /w/dx at unknown HEAD",
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

        _launch(recorder=recorder, heads=["a"] * 7)

        assert (len(recorder.spawned), recorder.lines[1:]) == (
            3,
            [
                "Dev page exited with 1 (1 in a row); restarting in 0s",
                "Dev page exited with 1 (2 in a row); restarting in 5s",
                "Dev page exited with 1 (3 in a row); restarting in 15s",
            ],
        )

    def test_restarts_once_the_backoff_deadline_passes(self) -> None:
        recorder = Recorder(
            children=[
                FakeChild(pid=10, exit_code=1),
                FakeChild(pid=11, exit_code=1),
                FakeChild(pid=12, exit_code=1),
                FakeChild(pid=13),
            ]
        )

        _launch(recorder=recorder, heads=["a"] * 8)

        assert len(recorder.spawned) == 4

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
    ("failures", "seconds"),
    [(0, 0.0), (1, 0.0), (2, 5.0), (3, 15.0), (4, 35.0), (5, 60.0), (20, 60.0), (10**6, 60.0)],
)
def test_backoff_doubles_up_to_a_cap_in_seconds(failures: int, seconds: float) -> None:
    assert dev_launcher.backoff_seconds(failures=failures) == seconds


def test_the_backoff_cap_does_not_scale_with_the_poll_interval() -> None:
    recorder = Recorder(children=[FakeChild(pid=10, exit_code=1)] * 9)
    stop = threading.Event()
    clock = TickClock()
    sequence = _heads(values=["a"] * 80, stop=stop)

    def read_head(*, checkout: Path) -> str | None:
        clock.now += 0.5
        return next(sequence)

    DevLauncher(
        command=["uv", "run"],
        checkout=CHECKOUT,
        announce=recorder.lines.append,
        spawner=recorder.spawn,  # type: ignore[arg-type]
        head_reader=read_head,
        killer=recorder.kill,
        clock=clock,
    ).run(stop=stop, interval=0)

    assert recorder.lines[-1] == "Dev page exited with 1 (4 in a row); restarting in 35s"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc")
def test_stopping_reaches_a_grandchild(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    stop = threading.Event()
    launcher = DevLauncher(
        command=["sh", "-c", f"sleep 300 & echo $! > {pid_file}; wait"],
        checkout=tmp_path,
        announce=lambda line: None,
        head_reader=lambda *, checkout: "a",
    )
    thread = threading.Thread(target=launcher.run, kwargs={"stop": stop, "interval": 0.05})
    thread.start()
    pid = _wait_for_pid(path=pid_file)
    stop.set()
    thread.join(timeout=dev_launcher.STOP_TIMEOUT_SECONDS + 5)

    assert _is_gone(pid=pid)


def _wait_for_pid(*, path: Path) -> int:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        text = path.read_text(encoding="utf-8").strip() if path.exists() else ""
        if text:
            return int(text)
        time.sleep(0.02)
    raise AssertionError(f"{path} never received the grandchild pid")


def _is_gone(*, pid: int) -> bool:
    deadline = time.monotonic() + 5
    stat = Path(f"/proc/{pid}/stat")
    while time.monotonic() < deadline:
        try:
            state = stat.read_text(encoding="utf-8").rsplit(")", 1)[1].split()[0]
        except (FileNotFoundError, ProcessLookupError):
            return True
        if state == "Z":
            return True
        time.sleep(0.02)
    return False


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

        head = dev_launcher.get_head(checkout=CHECKOUT, runner=runner)

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

        assert dev_launcher.get_head(checkout=CHECKOUT, runner=runner) is None


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
        "overwatch",
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
