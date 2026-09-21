"""Bounded retry policy for external calls (GH-1423).

Every external call in this codebase was a single attempt with a fixed
timeout: neither ``gh api`` nor the Slack transport backed off on a 429
or retried a plainly transient failure, so each caller up the stack
inherited zero resilience and none of them implemented retry itself.

This module holds the **decision** — is an outcome worth retrying, and
how long should the caller wait — and nothing else. The waiting is done
by the adopters, because the two call paths have incompatible shapes:
``_gh_api_raw`` is a coroutine over a subprocess, ``call_slack_api`` is
a synchronous ``urllib`` call. A shared driver would have to pick one.
Keeping the policy pure is also what lets it live under ``domain/``
(ADR-0008: no outward dependencies).

The bound is deliberate and small. GH-1288 established that the
transport ceiling, not caller patience, sets the limit — an unbounded
retry here would reintroduce exactly the long-wait failure that issue
removed from ``ci_check_status``.
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable
from dataclasses import dataclass, field

# 408 Request Timeout and 429 Too Many Requests are explicit "try again"
# signals; 5xx are server-side faults that a second attempt often clears.
# 4xx other than these two are the caller's fault and will fail identically
# however many times they are sent.
_RETRYABLE_STATUSES = frozenset({408, 429, 500, 502, 503, 504})

_HTTP_STATUS = re.compile(r"HTTP\s+(\d{3})\b", re.IGNORECASE)
_RETRY_AFTER = re.compile(r"Retry-After:\s*(\d+)", re.IGNORECASE)

# Matched against the transport's own error text when no HTTP status is
# present at all — the call never reached a server to be answered.
_NETWORK_FAULT = re.compile(
    r"connection (refused|reset|aborted)"
    r"|no route to host"
    r"|temporary failure in name resolution"
    r"|could not resolve host"
    r"|network is unreachable"
    r"|dial tcp"
    r"|EOF"
    r"|broken pipe"
    r"|TLS handshake",
    re.IGNORECASE,
)


def is_retryable_status(status: int) -> bool:
    """Is this HTTP status worth another attempt?

    For a caller that already holds the status as a number — an
    ``HTTPError``, a parsed response — rather than only as error text.
    """
    return status in _RETRYABLE_STATUSES


def http_status(text: str) -> int | None:
    """Return the HTTP status named in ``text``, or None if none is."""
    match = _HTTP_STATUS.search(text)
    return int(match.group(1)) if match else None


def retry_after_seconds(text: str) -> float | None:
    """Return the server's own ``Retry-After`` hint, when it gave one."""
    match = _RETRY_AFTER.search(text)
    return float(match.group(1)) if match else None


def is_retryable(text: str) -> bool:
    """Is this failure text worth another attempt?

    A recognised HTTP status decides on its own — a 404 is not more
    likely to exist on the second ask, and retrying it wastes the
    budget that a real 503 needs. Only when the text names no status at
    all does the network-fault wordlist get a say, because that is the
    shape of a call that never reached a server.
    """
    status = http_status(text)
    if status is not None:
        return status in _RETRYABLE_STATUSES
    return bool(_NETWORK_FAULT.search(text))


@dataclass(frozen=True)
class RetryPolicy:
    """How many further attempts to make, and how long to wait between.

    ``attempts`` counts total attempts, not retries: ``attempts=3`` means
    one call plus at most two more.
    """

    attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0
    jitter: Callable[[], float] = field(default=random.random, compare=False)

    def delay_for(self, *, attempt: int, retry_after: float | None = None) -> float:
        """Seconds to wait before the attempt after ``attempt`` (1-based).

        A server's ``Retry-After`` wins over the computed backoff, but is
        still clamped to ``max_delay``: an honest hint is better
        information than a guess, and an absurd one is not worth
        blocking a daemon worker on.

        Otherwise: exponential backoff with full jitter. Jitter is not
        decoration here — the case this exists for is several worktrees
        being throttled at once, and an unjittered backoff would march
        them all back in lockstep.
        """
        if retry_after is not None:
            return min(max(retry_after, 0.0), self.max_delay)
        backoff = min(self.base_delay * (2 ** max(attempt - 1, 0)), self.max_delay)
        return backoff * self.jitter()
