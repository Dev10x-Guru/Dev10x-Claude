"""GH-1423: bounded retry policy for external calls."""

from __future__ import annotations

import pytest

from dev10x.domain.retry import (
    RetryPolicy,
    http_status,
    is_retryable,
    is_retryable_status,
    retry_after_seconds,
)


class TestHttpStatus:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("gh: Not Found (HTTP 404)", 404),
            ("HTTP 429: API rate limit exceeded", 429),
            ("http 503 service unavailable", 503),
            ("no status here at all", None),
            ("", None),
            # A bare number must not be mistaken for a status.
            ("retried 500 times", None),
        ],
    )
    def test_parses_only_a_real_status(self, text, expected) -> None:
        assert http_status(text) == expected


class TestRetryAfterSeconds:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("Retry-After: 30", 30.0),
            ("retry-after:5", 5.0),
            ("HTTP 429 with no hint", None),
            ("", None),
        ],
    )
    def test_parses_the_server_hint(self, text, expected) -> None:
        assert retry_after_seconds(text) == expected


class TestIsRetryableStatus:
    @pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
    def test_transient_statuses_retry(self, status) -> None:
        assert is_retryable_status(status) is True

    @pytest.mark.parametrize("status", [200, 301, 400, 401, 403, 404, 409, 422])
    def test_caller_fault_statuses_do_not(self, status) -> None:
        assert is_retryable_status(status) is False


class TestIsRetryable:
    @pytest.mark.parametrize(
        "text",
        [
            "HTTP 429: API rate limit exceeded",
            "gh: server error (HTTP 502)",
            "HTTP 503",
        ],
    )
    def test_transient_http_failures_retry(self, text) -> None:
        assert is_retryable(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "gh: Not Found (HTTP 404)",
            "HTTP 422: field wasn't supplied",
            "HTTP 401: Bad credentials",
        ],
    )
    def test_terminal_http_failures_do_not(self, text) -> None:
        assert is_retryable(text) is False

    @pytest.mark.parametrize(
        "text",
        [
            "dial tcp 140.82.114.6:443: connect: connection refused",
            "Temporary failure in name resolution",
            "could not resolve host: api.github.com",
            "unexpected EOF",
            "net/http: TLS handshake timeout",
        ],
    )
    def test_network_faults_retry_when_no_status_is_named(self, text) -> None:
        assert is_retryable(text) is True

    def test_a_named_status_overrides_the_wordlist(self) -> None:
        """A 404 whose body happens to mention a network word is still a 404.

        Otherwise the wordlist could resurrect terminal failures and burn
        the budget a real 503 needs.
        """
        assert is_retryable("HTTP 404: no route to host") is False

    @pytest.mark.parametrize("text", ["", "something else entirely went wrong"])
    def test_unrecognised_failures_do_not_retry(self, text) -> None:
        assert is_retryable(text) is False


class TestRetryPolicy:
    @pytest.fixture
    def sut(self):
        """Jitter pinned to 1.0 so backoff is the exact computed value."""
        return RetryPolicy(attempts=4, base_delay=0.5, max_delay=8.0, jitter=lambda: 1.0)

    @pytest.mark.parametrize(
        "attempt, expected",
        [(1, 0.5), (2, 1.0), (3, 2.0), (4, 4.0), (5, 8.0), (6, 8.0)],
    )
    def test_backoff_doubles_then_clamps(self, sut, attempt, expected) -> None:
        assert sut.delay_for(attempt=attempt) == expected

    def test_server_hint_beats_computed_backoff(self, sut) -> None:
        assert sut.delay_for(attempt=1, retry_after=3.0) == 3.0

    def test_an_absurd_hint_is_clamped(self, sut) -> None:
        """A daemon worker must not park for an hour on a server's say-so."""
        assert sut.delay_for(attempt=1, retry_after=3600.0) == 8.0

    def test_a_negative_hint_does_not_become_a_negative_sleep(self, sut) -> None:
        assert sut.delay_for(attempt=1, retry_after=-5.0) == 0.0

    def test_jitter_spreads_callers_that_were_throttled_together(self) -> None:
        policy = RetryPolicy(base_delay=1.0, max_delay=8.0, jitter=lambda: 0.25)

        assert policy.delay_for(attempt=3) == pytest.approx(1.0)

    @pytest.mark.parametrize("attempts", [0, -1])
    def test_a_policy_that_would_never_run_is_refused(self, attempts: int) -> None:
        """Both adopters bind their result inside `for attempt in range(...)`.

        A zero skips the loop entirely, so the trailing return reads an
        unbound name — a NameError on the one call that needed the retry.
        """
        with pytest.raises(ValueError, match="at least 1"):
            RetryPolicy(attempts=attempts)

    def test_a_single_attempt_policy_is_allowed(self) -> None:
        """Retry disabled is a legitimate configuration, unlike zero."""
        assert RetryPolicy(attempts=1).attempts == 1

    def test_default_policy_is_bounded(self) -> None:
        """GH-1288: the transport ceiling sets the limit, not patience."""
        policy = RetryPolicy()
        worst_case = sum(policy.max_delay for _ in range(policy.attempts - 1))

        assert policy.attempts == 3
        assert worst_case <= 16.0
