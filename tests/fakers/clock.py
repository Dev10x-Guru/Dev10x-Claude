"""Shared fake monotonic clock for polling tests (GH-1885)."""

from __future__ import annotations


class FakeClock:
    def __init__(self, *, start: float = 0.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.advance(seconds)
