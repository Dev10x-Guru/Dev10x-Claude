"""One deadline-bounded poll loop for every waiting tool (GH-1852).

``pr_wait`` and ``wait_for`` each carried their own poll-until-done loop,
their own ``_sleep`` / ``_clock`` seams and their own wall-clock deadline,
so a budget fix had to land twice — and the deadline added in review on
GH-1833 reached only one of them first. They share this loop now, and
tests patch the two seams here once.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from dev10x.core.domain.transport_budget import tool_call_room

_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
_clock: Callable[[], float] = time.monotonic


@dataclass(frozen=True)
class Deadline:
    """A wall-clock end point, read through an injectable clock.

    ``clock`` is resolved on every reading rather than at construction,
    so a test that swaps the module clock after the deadline exists still
    drives it. Synchronous callers (``ci_check_status``'s script) pass
    their own clock.
    """

    ends_at: float
    clock: Callable[[], float] | None = None

    @classmethod
    def after(
        cls,
        *,
        seconds: float,
        clock: Callable[[], float] | None = None,
    ) -> Deadline:
        return cls(ends_at=(clock or _clock)() + seconds, clock=clock)

    @classmethod
    def for_tool_call(cls, *, overhead: float) -> Deadline:
        """What is left of one MCP call once ``overhead`` is set aside."""
        return cls.after(seconds=tool_call_room(overhead=overhead))

    def remaining(self) -> float:
        return max(0.0, self.ends_at - (self.clock or _clock)())

    def expired(self) -> bool:
        return self.remaining() <= 0


@dataclass(frozen=True)
class PollRun[T]:
    """How a poll loop ended: the last probe, its count, and why it stopped."""

    last: T
    polls: int
    done: bool


async def poll_until[T](
    *,
    probe: Callable[[], Awaitable[T]],
    done: Callable[[T], bool],
    deadline: Deadline,
    interval: float,
    max_polls: int | None = None,
) -> PollRun[T]:
    """Probe until ``done`` holds, the deadline passes, or the polls run out.

    The probe always runs at least once. The sleep never outlasts the
    deadline, so a slow probe eats into the wait instead of extending it.
    ``done`` is where a caller ends early on a condition that can no
    longer hold, as well as on one that does.
    """
    polls = 0
    while True:
        polls += 1
        value = await probe()
        if done(value):
            return PollRun(last=value, polls=polls, done=True)
        remaining = deadline.remaining()
        if remaining <= 0 or (max_polls is not None and polls >= max_polls):
            return PollRun(last=value, polls=polls, done=False)
        await _sleep(min(interval, remaining))
