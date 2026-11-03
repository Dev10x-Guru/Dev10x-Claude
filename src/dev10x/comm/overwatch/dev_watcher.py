"""Run the dev Overwatch page while a checkout is pinned (GH-1804).

The release ``serve`` reads the ``dev:`` pin in ``overwatch.yaml`` on every
poll and keeps one ``DevLauncher`` running for it: pinning starts it,
re-pinning restarts it, unpinning stops it. One systemd unit therefore
covers both pages, and the pin is the only switch.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from dev10x.comm.overwatch.dev_checkout import DevCheckout, DevCheckoutError, read_dev_checkout
from dev10x.comm.overwatch.dev_launcher import DevLauncher, child_command

log = logging.getLogger(__name__)


class Launcher(Protocol):
    def run(self, *, stop: threading.Event, interval: float) -> None: ...


LauncherFactory = Callable[[DevCheckout], Launcher]


def launcher_factory(
    *,
    uv: str,
    interval: float,
    kb_root: Path,
    bus_root: Path,
    relay_mailbox: str,
    announce: Callable[[str], None],
) -> LauncherFactory:
    def make(dev: DevCheckout) -> Launcher:
        return DevLauncher(
            command=child_command(
                dev=dev,
                uv=uv,
                interval=interval,
                kb_root=kb_root,
                bus_root=bus_root,
                relay_mailbox=relay_mailbox,
            ),
            checkout=dev.checkout,
            announce=announce,
        )

    return make


@dataclass
class DevPinWatcher:
    make_launcher: LauncherFactory
    announce: Callable[[str], None]
    read_pin: Callable[[], DevCheckout | None] = read_dev_checkout
    _pin: DevCheckout | None = field(default=None, init=False)
    _thread: threading.Thread | None = field(default=None, init=False)
    _halt: threading.Event = field(default_factory=threading.Event, init=False)
    _unusable: str | None = field(default=None, init=False)

    def run(self, *, stop: threading.Event, interval: float) -> None:
        try:
            while True:
                try:
                    self.tick(interval=interval)
                except Exception:
                    log.exception("overwatch dev pin tick failed")
                if stop.wait(interval):
                    return
        finally:
            self._stop_launcher()

    def tick(self, *, interval: float) -> None:
        try:
            pin = self.read_pin()
        except DevCheckoutError as exc:
            self._report_unusable(reason=str(exc))
            return
        self._unusable = None
        if pin is None and self._pin is None:
            return
        if pin == self._pin and self._launcher_alive():
            return
        self._announce_change(pin=pin)
        self._stop_launcher()
        self._pin = pin
        if pin is not None:
            self._start_launcher(pin=pin, interval=interval)

    def _report_unusable(self, *, reason: str) -> None:
        if reason == self._unusable:
            return
        self._unusable = reason
        state = "keeps running" if self._launcher_alive() else "stays off"
        self.announce(f"The dev checkout pin is unusable: {reason}; the dev page {state}")

    def _announce_change(self, *, pin: DevCheckout | None) -> None:
        if pin is None:
            self.announce("Dev checkout unpinned; stopping the dev page")
        elif self._pin is None:
            self.announce(
                f"Dev checkout pinned: {pin.checkout} on port {pin.port}; starting the dev page"
            )
        elif pin != self._pin:
            self.announce(
                f"Dev pin changed to {pin.checkout} on port {pin.port}; restarting the dev page"
            )
        else:
            self.announce("The dev page launcher stopped; starting it again")

    def _launcher_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _start_launcher(self, *, pin: DevCheckout, interval: float) -> None:
        self._halt = threading.Event()
        self._thread = threading.Thread(
            target=self._run_launcher,
            kwargs={"launcher": self.make_launcher(pin), "halt": self._halt, "interval": interval},
            name="overwatch-dev-launcher",
            daemon=True,
        )
        self._thread.start()

    def _run_launcher(
        self,
        *,
        launcher: Launcher,
        halt: threading.Event,
        interval: float,
    ) -> None:
        try:
            launcher.run(stop=halt, interval=interval)
        except Exception as exc:
            log.exception("overwatch dev launcher failed")
            self.announce(f"The dev page launcher failed: {exc}")

    def _stop_launcher(self) -> None:
        if self._thread is None:
            return
        self._halt.set()
        self._thread.join()
        self._thread = None
