"""The shared deadline-bounded poll loop (GH-1852)."""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from dev10x.domain.transport_budget import MAX_TOOL_CALL_SECONDS

polling = importlib.import_module("dev10x.core.domain.polling")


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture(autouse=True)
def clock() -> Iterator[FakeClock]:
    fake = FakeClock()
    with (
        patch.object(polling, "_clock", new=fake),
        patch.object(polling, "_sleep", new=fake.sleep),
    ):
        yield fake


class TestDeadline:
    def test_remaining_counts_down_with_the_clock(self, clock: FakeClock) -> None:
        deadline = polling.Deadline.after(seconds=10)
        clock.now = 4

        assert deadline.remaining() == 6
        assert deadline.expired() is False

    def test_remaining_never_goes_negative(self, clock: FakeClock) -> None:
        deadline = polling.Deadline.after(seconds=10)
        clock.now = 25

        assert deadline.remaining() == 0
        assert deadline.expired() is True

    def test_tool_call_deadline_sets_the_overhead_aside(self) -> None:
        deadline = polling.Deadline.for_tool_call(overhead=60)

        assert deadline.remaining() == MAX_TOOL_CALL_SECONDS - 60

    def test_an_explicit_clock_wins_over_the_module_clock(self) -> None:
        ticks = iter([100.0, 103.0])
        deadline = polling.Deadline.after(seconds=5, clock=lambda: next(ticks))

        assert deadline.remaining() == 2


class TestPollUntil:
    @pytest.mark.asyncio
    async def test_returns_as_soon_as_done_holds(self, clock: FakeClock) -> None:
        values = iter([1, 2, 3])

        run = await polling.poll_until(
            probe=AsyncMock(side_effect=lambda: next(values)),
            done=lambda value: value == 2,
            deadline=polling.Deadline.after(seconds=100),
            interval=5,
        )

        assert (run.last, run.polls, run.done) == (2, 2, True)
        assert clock.sleeps == [5]

    @pytest.mark.asyncio
    async def test_stops_at_the_deadline(self, clock: FakeClock) -> None:
        run = await polling.poll_until(
            probe=AsyncMock(return_value=0),
            done=lambda value: False,
            deadline=polling.Deadline.after(seconds=12),
            interval=5,
        )

        assert (run.polls, run.done) == (4, False)
        assert clock.sleeps == [5, 5, 2]

    @pytest.mark.asyncio
    async def test_stops_when_the_polls_run_out(self, clock: FakeClock) -> None:
        run = await polling.poll_until(
            probe=AsyncMock(return_value=0),
            done=lambda value: False,
            deadline=polling.Deadline.after(seconds=1000),
            interval=5,
            max_polls=3,
        )

        assert (run.polls, run.done) == (3, False)
        assert clock.sleeps == [5, 5]

    @pytest.mark.asyncio
    async def test_probes_once_even_with_no_time_left(self, clock: FakeClock) -> None:
        probe = AsyncMock(return_value=0)

        run = await polling.poll_until(
            probe=probe,
            done=lambda value: False,
            deadline=polling.Deadline.after(seconds=0),
            interval=5,
        )

        assert run.polls == 1
        probe.assert_awaited_once()
        assert clock.sleeps == []
