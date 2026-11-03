"""Tests for the dev pin watcher behind the single Overwatch unit (GH-1804)."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from dev10x.comm.overwatch.dev_checkout import DevCheckout, DevCheckoutError
from dev10x.comm.overwatch.dev_launcher import DevLauncher
from dev10x.comm.overwatch.dev_watcher import DevPinWatcher, launcher_factory

FIRST = DevCheckout(checkout=Path("/w/first"), port=8766)
SECOND = DevCheckout(checkout=Path("/w/second"), port=8767)
TIMEOUT = 5.0

PinValue = DevCheckout | None | Exception


class FakeLauncher:
    def __init__(self, *, pin: DevCheckout, mode: str) -> None:
        self.pin = pin
        self.mode = mode
        self.started = threading.Event()
        self.halted = threading.Event()

    def run(self, *, stop: threading.Event, interval: float) -> None:
        self.started.set()
        if self.mode == "crash":
            raise RuntimeError("boom")
        if self.mode == "wait":
            stop.wait()
        self.halted.set()


class Factory:
    def __init__(self, *, mode: str = "wait") -> None:
        self.mode = mode
        self.made: list[FakeLauncher] = []
        self.any_made = threading.Event()

    def __call__(self, pin: DevCheckout) -> FakeLauncher:
        launcher = FakeLauncher(pin=pin, mode=self.mode)
        self.made.append(launcher)
        self.any_made.set()
        return launcher


class Pins:
    def __init__(self, *, values: list[PinValue]) -> None:
        self.values = iter(values)
        self.reads = 0
        self.second_read = threading.Event()

    def __call__(self) -> DevCheckout | None:
        self.reads += 1
        if self.reads >= 2:
            self.second_read.set()
        value = next(self.values)
        if isinstance(value, Exception):
            raise value
        return value


Build = Callable[..., DevPinWatcher]


@pytest.fixture
def lines() -> list[str]:
    return []


@pytest.fixture
def build(lines: list[str]) -> Iterator[Build]:
    built: list[DevPinWatcher] = []

    def make(*, pins: list[PinValue], factory: Factory) -> DevPinWatcher:
        watcher = DevPinWatcher(
            make_launcher=factory, announce=lines.append, read_pin=Pins(values=pins)
        )
        built.append(watcher)
        return watcher

    yield make
    for watcher in built:
        watcher._stop_launcher()


def _settle(*, watcher: DevPinWatcher) -> None:
    thread = watcher._thread
    assert thread is not None
    thread.join(timeout=TIMEOUT)


class TestTick:
    def test_no_pin_starts_nothing(self, build: Build, lines: list[str]) -> None:
        factory = Factory()
        watcher = build(pins=[None, None], factory=factory)

        watcher.tick(interval=0)
        watcher.tick(interval=0)

        assert (factory.made, lines) == ([], [])

    def test_a_new_pin_starts_the_dev_page(self, build: Build, lines: list[str]) -> None:
        factory = Factory()
        watcher = build(pins=[FIRST], factory=factory)

        watcher.tick(interval=0)

        assert (factory.made[0].started.wait(timeout=TIMEOUT), factory.made[0].pin, lines) == (
            True,
            FIRST,
            ["Dev checkout pinned: /w/first on port 8766; starting the dev page"],
        )

    def test_an_unchanged_pin_keeps_the_dev_page(self, build: Build, lines: list[str]) -> None:
        factory = Factory()
        watcher = build(pins=[FIRST, FIRST], factory=factory)

        watcher.tick(interval=0)
        factory.made[0].started.wait(timeout=TIMEOUT)
        watcher.tick(interval=0)

        assert (len(factory.made), len(lines)) == (1, 1)

    def test_a_changed_pin_restarts_the_dev_page(self, build: Build, lines: list[str]) -> None:
        factory = Factory()
        watcher = build(pins=[FIRST, SECOND], factory=factory)

        watcher.tick(interval=0)
        factory.made[0].started.wait(timeout=TIMEOUT)
        watcher.tick(interval=0)

        assert (factory.made[0].halted.is_set(), factory.made[1].pin, lines[1]) == (
            True,
            SECOND,
            "Dev pin changed to /w/second on port 8767; restarting the dev page",
        )

    def test_unpinning_stops_the_dev_page(self, build: Build, lines: list[str]) -> None:
        factory = Factory()
        watcher = build(pins=[FIRST, None], factory=factory)

        watcher.tick(interval=0)
        factory.made[0].started.wait(timeout=TIMEOUT)
        watcher.tick(interval=0)

        assert (factory.made[0].halted.is_set(), watcher._thread, lines[1]) == (
            True,
            None,
            "Dev checkout unpinned; stopping the dev page",
        )

    def test_an_unusable_pin_is_announced_once_and_starts_nothing(
        self, build: Build, lines: list[str]
    ) -> None:
        error = DevCheckoutError("not valid YAML")
        factory = Factory()
        watcher = build(pins=[error, error], factory=factory)

        watcher.tick(interval=0)
        watcher.tick(interval=0)

        assert (factory.made, lines) == (
            [],
            ["The dev checkout pin is unusable: not valid YAML; the dev page stays off"],
        )

    def test_an_unusable_pin_leaves_a_running_dev_page_alone(
        self, build: Build, lines: list[str]
    ) -> None:
        factory = Factory()
        watcher = build(pins=[FIRST, DevCheckoutError("gone")], factory=factory)

        watcher.tick(interval=0)
        factory.made[0].started.wait(timeout=TIMEOUT)
        watcher.tick(interval=0)

        assert (factory.made[0].halted.is_set(), lines[1]) == (
            False,
            "The dev checkout pin is unusable: gone; the dev page keeps running",
        )

    def test_a_recovered_pin_announces_the_next_failure_again(
        self, build: Build, lines: list[str]
    ) -> None:
        error = DevCheckoutError("bad")
        watcher = build(pins=[error, None, error], factory=Factory())

        watcher.tick(interval=0)
        watcher.tick(interval=0)
        watcher.tick(interval=0)

        assert len(lines) == 2

    def test_a_launcher_that_ended_is_started_again(self, build: Build, lines: list[str]) -> None:
        factory = Factory(mode="exit")
        watcher = build(pins=[FIRST, FIRST], factory=factory)

        watcher.tick(interval=0)
        _settle(watcher=watcher)
        watcher.tick(interval=0)

        assert (len(factory.made), lines[1]) == (
            2,
            "The dev page launcher stopped; starting it again",
        )

    def test_a_crashing_launcher_is_reported(self, build: Build, lines: list[str]) -> None:
        watcher = build(pins=[FIRST], factory=Factory(mode="crash"))

        watcher.tick(interval=0)
        _settle(watcher=watcher)

        assert lines[1] == "The dev page launcher failed: boom"


class TestRun:
    def test_stopping_stops_the_dev_page(self, lines: list[str]) -> None:
        factory = Factory()
        watcher = DevPinWatcher(
            make_launcher=factory, announce=lines.append, read_pin=lambda: FIRST
        )
        stop = threading.Event()
        thread = threading.Thread(
            target=watcher.run, kwargs={"stop": stop, "interval": 0.01}, daemon=True
        )

        thread.start()
        factory.any_made.wait(timeout=TIMEOUT)
        started = factory.made[0].started.wait(timeout=TIMEOUT)
        stop.set()
        thread.join(timeout=TIMEOUT)

        assert (started, factory.made[0].halted.is_set(), thread.is_alive()) == (
            True,
            True,
            False,
        )

    def test_a_failing_tick_does_not_end_the_loop(self, lines: list[str]) -> None:
        pins = Pins(values=[OSError("disk")] + [None] * 1000)
        watcher = DevPinWatcher(make_launcher=Factory(), announce=lines.append, read_pin=pins)
        stop = threading.Event()
        thread = threading.Thread(
            target=watcher.run, kwargs={"stop": stop, "interval": 0.01}, daemon=True
        )

        thread.start()
        survived = pins.second_read.wait(timeout=TIMEOUT)
        stop.set()
        thread.join(timeout=TIMEOUT)

        assert (survived, thread.is_alive()) == (True, False)


def test_launcher_factory_runs_the_checkout_code(tmp_path: Path) -> None:
    make = launcher_factory(
        uv="/bin/uv",
        interval=2.0,
        kb_root=tmp_path / "kb",
        bus_root=tmp_path / "bus",
        relay_mailbox="relay",
        announce=print,
    )

    launcher = make(FIRST)

    assert (
        (
            isinstance(launcher, DevLauncher),
            launcher.checkout,  # type: ignore[attr-defined]
            launcher.command[:4],  # type: ignore[attr-defined]
            launcher.command[-1],  # type: ignore[attr-defined]
        )
        == (True, FIRST.checkout, ["/bin/uv", "run", "--project", "/w/first"], "relay")
    )
