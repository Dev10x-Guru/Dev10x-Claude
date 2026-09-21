"""GH-1423: `_gh_api_raw` retries transient failures, and only those.

Every `gh` call used to be a single attempt, so a rate limit or a network
blip reached the caller as a hard failure. These tests patch `async_run`
— the subprocess boundary underneath `_gh_api_raw` — so the retry loop
itself is what is under test.
"""

from __future__ import annotations

import subprocess

import pytest

import dev10x.github as gh


def _completed(
    *, returncode: int, stderr: str = "", stdout: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["gh", "api"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


@pytest.fixture(autouse=True)
def no_real_sleeping(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Make backoff free, but keep the real attempt count."""
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(gh.asyncio, "sleep", fake_sleep)
    return slept


class TestGhApiRawRetries:
    @staticmethod
    def _replaying(outcomes: list, calls: list) -> object:
        """`async_run` stub that returns `outcomes` in order."""

        async def fake_async_run(**kwargs) -> subprocess.CompletedProcess[str]:
            calls.append(kwargs)
            return outcomes[min(len(calls) - 1, len(outcomes) - 1)]

        return fake_async_run

    @pytest.mark.asyncio
    async def test_a_rate_limit_then_success_delivers(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list = []
        outcomes = [
            _completed(returncode=1, stderr="HTTP 429: API rate limit exceeded"),
            _completed(returncode=0, stdout='{"ok": true}'),
        ]
        monkeypatch.setattr(gh, "async_run", self._replaying(outcomes, calls))

        result = await gh._gh_api_raw("repos/o/r/pulls/1")

        assert len(calls) == 2
        assert result.returncode == 0
        assert result.stdout == '{"ok": true}'

    @pytest.mark.asyncio
    async def test_success_on_the_first_call_costs_nothing_extra(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list = []
        monkeypatch.setattr(gh, "async_run", self._replaying([_completed(returncode=0)], calls))

        await gh._gh_api_raw("repos/o/r")

        assert len(calls) == 1

    @pytest.mark.parametrize(
        "stderr",
        [
            "HTTP 429: API rate limit exceeded",
            "gh: server error (HTTP 502)",
            "HTTP 503 Service Unavailable",
            "dial tcp 140.82.114.6:443: connect: connection refused",
        ],
    )
    @pytest.mark.asyncio
    async def test_transient_failures_exhaust_the_budget(
        self,
        monkeypatch: pytest.MonkeyPatch,
        stderr: str,
    ) -> None:
        calls: list = []
        monkeypatch.setattr(
            gh,
            "async_run",
            self._replaying([_completed(returncode=1, stderr=stderr)], calls),
        )

        result = await gh._gh_api_raw("repos/o/r")

        assert len(calls) == gh._GH_RETRY_POLICY.attempts
        assert result.returncode == 1

    @pytest.mark.parametrize(
        "stderr",
        [
            "gh: Not Found (HTTP 404)",
            "HTTP 422: field wasn't supplied",
            "HTTP 401: Bad credentials",
        ],
    )
    @pytest.mark.asyncio
    async def test_terminal_failures_are_not_retried(
        self,
        monkeypatch: pytest.MonkeyPatch,
        stderr: str,
    ) -> None:
        """A 404 is not more likely to exist on the second ask."""
        calls: list = []
        monkeypatch.setattr(
            gh,
            "async_run",
            self._replaying([_completed(returncode=1, stderr=stderr)], calls),
        )

        await gh._gh_api_raw("repos/o/r")

        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_our_own_timeout_is_not_retried(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """GH-1288: the wait was bounded on purpose.

        Re-running a timed-out call multiplies that bound by the attempt
        count, which is the long-wait failure that issue removed.
        """
        calls: list = []
        monkeypatch.setattr(
            gh,
            "async_run",
            self._replaying([_completed(returncode=-1, stderr="Process timed out")], calls),
        )

        result = await gh._gh_api_raw("repos/o/r")

        assert len(calls) == 1
        assert result.returncode == -1

    @pytest.mark.asyncio
    async def test_the_server_retry_after_hint_is_honoured(
        self,
        monkeypatch: pytest.MonkeyPatch,
        no_real_sleeping: list[float],
    ) -> None:
        calls: list = []
        monkeypatch.setattr(
            gh,
            "async_run",
            self._replaying([_completed(returncode=1, stderr="HTTP 429\nRetry-After: 2")], calls),
        )

        await gh._gh_api_raw("repos/o/r")

        assert no_real_sleeping == [2.0, 2.0]

    @pytest.mark.asyncio
    async def test_backoff_stays_within_the_policy_ceiling(
        self,
        monkeypatch: pytest.MonkeyPatch,
        no_real_sleeping: list[float],
    ) -> None:
        calls: list = []
        monkeypatch.setattr(
            gh,
            "async_run",
            self._replaying([_completed(returncode=1, stderr="HTTP 503")], calls),
        )

        await gh._gh_api_raw("repos/o/r")

        assert len(no_real_sleeping) == gh._GH_RETRY_POLICY.attempts - 1
        assert all(d <= gh._GH_RETRY_POLICY.max_delay for d in no_real_sleeping)
