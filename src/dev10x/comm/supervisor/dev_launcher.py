"""Keep the dev supervisor page running the checkout's newest commit (GH-1765).

The launcher runs from the installed ``dev10x`` and only starts, watches
and restarts a child that runs the checkout's own code through
``uv run --project``. A broken commit can crash the child but not the
launcher, so the next commit is still picked up.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from dev10x.comm.supervisor import paths
from dev10x.comm.supervisor.dev_checkout import DevCheckout
from dev10x.subprocess_utils import run

HEAD_TIMEOUT_SECONDS = 10.0
STOP_TIMEOUT_SECONDS = 10.0
MAX_BACKOFF_TICKS = 11

Runner = Callable[..., subprocess.CompletedProcess[str]]
Spawner = Callable[..., subprocess.Popen[bytes]]
Killer = Callable[[int, int], None]


def read_head(*, checkout: Path, runner: Runner = run) -> str | None:
    try:
        result = runner(
            ["git", "rev-parse", "HEAD"],
            cwd=str(checkout),
            capture_output=True,
            text=True,
            check=False,
            timeout=HEAD_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    head = result.stdout.strip()
    return head if result.returncode == 0 and head else None


def child_command(
    *,
    dev: DevCheckout,
    uv: str,
    interval: float,
    kb_root: Path,
    bus_root: Path,
    relay_mailbox: str,
) -> list[str]:
    return [
        uv,
        "run",
        "--project",
        str(dev.checkout),
        "dev10x",
        "supervisor",
        "serve",
        "--instance",
        paths.Instance.DEV.value,
        "--port",
        str(dev.port),
        "--interval",
        str(interval),
        "--kb-root",
        str(kb_root),
        "--bus-root",
        str(bus_root),
        "--relay-mailbox",
        relay_mailbox,
    ]


@dataclass
class DevLauncher:
    command: list[str]
    checkout: Path
    announce: Callable[[str], None]
    spawner: Spawner = subprocess.Popen
    head_reader: Callable[..., str | None] = read_head
    killer: Killer = os.killpg

    def _start(self) -> subprocess.Popen[bytes] | None:
        try:
            return self.spawner(self.command, cwd=str(self.checkout), start_new_session=True)
        except OSError as exc:
            self.announce(f"Cannot start the dev page: {exc}; retrying")
            return None

    def _signal(self, *, child: subprocess.Popen[bytes], signum: int) -> None:
        try:
            self.killer(child.pid, signum)
        except ProcessLookupError:
            return

    def _stop(self, *, child: subprocess.Popen[bytes] | None) -> None:
        if child is None or child.poll() is not None:
            return
        self._signal(child=child, signum=signal.SIGTERM)
        try:
            child.wait(timeout=STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            self._signal(child=child, signum=signal.SIGKILL)
            child.wait()

    def _note_head(self, *, current: str | None, previous: str | None, head: str | None) -> None:
        if current is None and previous is not None:
            self.announce(
                f"Cannot read HEAD of {self.checkout} (`git rev-parse HEAD` failed); "
                f"the dev page stays on {head}"
            )
        elif current is not None and previous is None:
            self.announce(f"HEAD of {self.checkout} is readable again at {current}")

    def run(self, *, stop: threading.Event, interval: float) -> None:
        head = self.head_reader(checkout=self.checkout)
        self.announce(f"Dev supervisor page from {self.checkout} at {head or 'unknown HEAD'}")
        previous = head
        child = self._start()
        failures = 0
        wait_ticks = 0
        try:
            while not stop.wait(interval):
                current = self.head_reader(checkout=self.checkout)
                self._note_head(current=current, previous=previous, head=head)
                previous = current
                if current is not None and head is None:
                    head = current
                elif current is not None and current != head:
                    self.announce(f"Checkout moved to {current}; restarting the dev page")
                    self._stop(child=child)
                    head = current
                    failures = wait_ticks = 0
                    child = self._start()
                elif child is not None and child.poll() is None:
                    failures = 0
                elif child is not None:
                    failures += 1
                    wait_ticks = backoff_ticks(failures=failures)
                    self.announce(
                        f"Dev page exited with {child.returncode} ({failures} in a row); "
                        f"restarting in {(wait_ticks + 1) * interval:g}s"
                    )
                    child = None
                elif wait_ticks > 0:
                    wait_ticks -= 1
                else:
                    child = self._start()
                    if child is None:
                        failures += 1
                        wait_ticks = backoff_ticks(failures=failures)
        finally:
            self._stop(child=child)


def backoff_ticks(*, failures: int) -> int:
    return min(2 ** max(failures - 1, 0) - 1, MAX_BACKOFF_TICKS)
