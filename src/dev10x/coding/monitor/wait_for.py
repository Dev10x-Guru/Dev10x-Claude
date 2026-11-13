"""Wait for a local condition inside one bounded tool call (GH-1833).

The companion of ``pr_wait`` for conditions that live on this machine: a
file appears, a file gains some text, a URL answers, a process exits, a
moment arrives. The result is ``{met, observed, timed_out}`` rather than
an exit code, so a caller never has to guess what a non-zero meant.

The timeout is clamped by ``clamp_tool_timeout`` (GH-1288); a wait that
genuinely needs longer belongs in a background Monitor, not a longer
blocking call.
"""

from __future__ import annotations

import asyncio
import http.client
import ipaddress
import math
import os
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dev10x.core.domain import polling
from dev10x.core.mcp.daemon import is_pid_alive
from dev10x.domain.common.result import Result, err, ok
from dev10x.domain.transport_budget import clamp_tool_timeout
from dev10x.subprocess_utils import async_run, effective_cwd

KINDS: tuple[str, ...] = ("file", "file_text", "regex", "http", "process_gone", "time")

_NEEDS_PATTERN = frozenset({"file_text", "regex"})
_HTTP_SCHEMES = ("http://", "https://")
_PROBE_TIMEOUT_SECONDS = 10.0
_MIN_POLL_INTERVAL = 0.1
_MAX_READ_BYTES = 4 * 1024 * 1024
_EXCERPT_CHARS = 200


def _now() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(frozen=True)
class Probe:
    """One look at the condition.

    ``unreachable`` marks a probe that can never succeed however long it
    waits — no ``pgrep``, a target that is not a regular file, a file it
    may not read — so the wait ends at once instead of sitting out the
    timeout (GH-1852). A refused connection is NOT unreachable: waiting
    for a server to start listening is what ``http`` is for.
    """

    met: bool
    observed: dict[str, Any]
    unreachable: bool = False


def _resolve_path(*, target: str) -> Path:
    path = Path(target).expanduser()
    if path.is_absolute():
        return path
    return Path(effective_cwd() or os.getcwd()) / path


def _read_text(*, path: Path) -> tuple[str | None, str | None]:
    """The file's leading text, or why it could not be read.

    A FIFO or device would block ``open`` with no deadline, so anything
    that is not a regular file is refused before it is opened.
    """
    try:
        if not path.exists():
            return None, None
        if not path.is_file():
            return None, "not a regular file"
        with path.open("rb") as handle:
            return handle.read(_MAX_READ_BYTES).decode("utf-8", errors="replace"), None
    except OSError as exc:
        return None, str(exc)[:_EXCERPT_CHARS]


def _probe_file(*, target: str) -> Probe:
    path = _resolve_path(target=target)
    exists = path.exists()
    return Probe(met=exists, observed={"path": str(path), "exists": exists})


def _probe_text(*, target: str, pattern: str, compiled: re.Pattern[str] | None) -> Probe:
    path = _resolve_path(target=target)
    text, error = _read_text(path=path)
    observed: dict[str, Any] = {"path": str(path), "exists": text is not None or bool(error)}
    if error:
        observed["error"] = error
    if text is None:
        return Probe(met=False, observed=observed, unreachable=bool(error))
    if compiled is None:
        found = pattern in text
        observed["match"] = pattern if found else None
        return Probe(met=found, observed=observed)
    match = compiled.search(text)
    observed["match"] = match.group(0)[:_EXCERPT_CHARS] if match else None
    return Probe(met=match is not None, observed=observed)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Report a redirect's own status instead of following it (GH-1885).

    A 3xx already means "the server is up", and following it would let
    a local endpoint bounce the probe to a host the caller never named.
    """

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _is_link_local(*, address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    return (mapped or ip).is_link_local


class _LinkLocalRefused(Exception):
    """The probe connected to a link-local address and sent no request.

    Not an ``OSError``, so urllib does not fold it into the ordinary
    connection failures that keep a wait polling.
    """


def _guarded_create_connection(address: Any, *args: Any, **kwargs: Any) -> socket.socket:
    """Open the socket, then refuse it if the peer is link-local (GH-1885).

    169.254.0.0/16 holds the instance-metadata address most clouds use,
    which an agent-driven probe has no reason to reach. Checking the
    address the socket actually connected to, rather than a separate DNS
    lookup, leaves no window for a name to resolve differently between
    the check and the request. Loopback and private ranges stay allowed:
    waiting for a local server to start is what ``http`` is for.
    """
    sock = socket.create_connection(address, *args, **kwargs)
    peer = str(sock.getpeername()[0])
    if _is_link_local(address=peer):
        sock.close()
        raise _LinkLocalRefused(f"refused: connected to link-local address {peer}")
    return sock


class _GuardedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._create_connection = _guarded_create_connection


class _GuardedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._create_connection = _guarded_create_connection


class _GuardedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(_GuardedHTTPConnection, req)


class _GuardedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self) -> None:
        self._tls = ssl.create_default_context()
        super().__init__(context=self._tls)

    def https_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(_GuardedHTTPSConnection, req, context=self._tls)


def _build_opener() -> urllib.request.OpenerDirector:
    """An opener that connects directly, guarded, without redirects.

    An empty ``ProxyHandler`` stands in for the default one, which would
    read ``HTTP_PROXY`` and send the request through a proxy whose own
    address is all the guard would see.
    """
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirect,
        _GuardedHTTPHandler,
        _GuardedHTTPSHandler,
    )


_OPENER = _build_opener()
_open = _OPENER.open


def _http_status(*, url: str) -> tuple[int | None, str | None]:
    request = urllib.request.Request(url, method="GET")
    try:
        with _open(request, timeout=_PROBE_TIMEOUT_SECONDS) as response:
            return int(response.status), None
    except urllib.error.HTTPError as exc:
        return int(exc.code), None
    except (http.client.HTTPException, OSError, ValueError) as exc:
        return None, str(exc)[:_EXCERPT_CHARS]


async def _probe_http(*, target: str, expect_status: int | None) -> Probe:
    try:
        status, error = await asyncio.to_thread(_http_status, url=target)
    except _LinkLocalRefused as exc:
        return Probe(
            met=False,
            observed={"url": target, "status": None, "error": str(exc)},
            unreachable=True,
        )
    if status is None:
        met = False
    elif expect_status is not None:
        met = status == expect_status
    else:
        met = 200 <= status < 400
    return Probe(met=met, observed={"url": target, "status": status, "error": error})


async def _probe_process(*, target: str) -> Probe:
    if target.isdigit():
        alive = is_pid_alive(pid=int(target))
        return Probe(met=not alive, observed={"pid": int(target), "alive": alive})
    try:
        result = await async_run(
            args=["pgrep", "-f", "--", target], timeout=_PROBE_TIMEOUT_SECONDS
        )
    except OSError as exc:
        return Probe(
            met=False,
            observed={"pattern": target, "error": f"pgrep unavailable: {exc}"},
            unreachable=True,
        )
    if result.returncode not in (0, 1):
        # A negative code is our own probe timeout, which may pass; a
        # positive one is pgrep rejecting the pattern, which will not.
        return Probe(
            met=False,
            observed={"pattern": target, "error": (result.stderr or "pgrep failed").strip()},
            unreachable=result.returncode > 1,
        )
    pids = [int(line) for line in result.stdout.split() if line.isdigit()]
    return Probe(met=not pids, observed={"pattern": target, "pids": pids})


def _is_http_url(*, target: str) -> bool:
    """A URL ``urlopen`` can at least attempt; a bad one never would.

    Checked up front so a malformed port or a missing host is a refused
    argument, not a probe that fails for the whole timeout (GH-1852).
    """
    if not target.startswith(_HTTP_SCHEMES):
        return False
    try:
        parts = urllib.parse.urlsplit(target)
        parts.port  # noqa: B018 — the property raises on a malformed port
    except ValueError:
        return False
    return bool(parts.hostname)


def _parse_moment(*, target: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(target)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _validate(
    *,
    kind: str,
    target: str,
    pattern: str | None,
    timeout: float,
    poll_interval: float,
) -> str | None:
    if kind not in KINDS:
        return f"kind must be one of {', '.join(KINDS)}, got {kind!r}"
    if not target.strip():
        return "target must not be empty"
    if not math.isfinite(timeout) or timeout < 0:
        return f"timeout must be a finite, non-negative number, got {timeout}"
    if not math.isfinite(poll_interval):
        return f"poll_interval must be a finite number, got {poll_interval}"
    if kind in _NEEDS_PATTERN and not pattern:
        return f"kind={kind!r} needs a 'pattern'"
    if kind == "http" and not _is_http_url(target=target):
        return f"kind='http' needs an http(s) URL with a host, got {target!r}"
    if kind == "http" and _is_link_local(address=urllib.parse.urlsplit(target).hostname or ""):
        return f"kind='http' refuses a link-local host, got {target!r}"
    if kind == "time" and _parse_moment(target=target) is None:
        return f"kind='time' needs an ISO-8601 timestamp, got {target!r}"
    return None


async def _probe(
    *,
    kind: str,
    target: str,
    pattern: str,
    compiled: re.Pattern[str] | None,
    expect_status: int | None,
) -> Probe:
    if kind == "file":
        return _probe_file(target=target)
    if kind in _NEEDS_PATTERN:
        return await asyncio.to_thread(
            _probe_text, target=target, pattern=pattern, compiled=compiled
        )
    if kind == "http":
        return await _probe_http(target=target, expect_status=expect_status)
    return await _probe_process(target=target)


async def _wait_for_time(*, moment: datetime, timeout: float) -> dict[str, Any]:
    remaining = (moment - _now()).total_seconds()
    if remaining > 0:
        await polling._sleep(min(remaining, timeout))
    met = _now() >= moment
    return {
        "met": met,
        "unreachable": False,
        "observed": {"target": moment.isoformat(), "now": _now().isoformat()},
        "polls": 1,
    }


async def wait_for(
    *,
    kind: str,
    target: str,
    timeout: float = 300,
    pattern: str | None = None,
    poll_interval: float = 2.0,
    expect_status: int | None = None,
) -> Result[dict[str, Any]]:
    """Poll a local condition until it holds or the timeout ends.

    Args:
        kind: One of ``KINDS``.
        target: A path (``file`` / ``file_text`` / ``regex``, relative
            paths resolve against the caller's cwd), an http(s) URL
            (``http``), a PID or ``pgrep -f`` pattern (``process_gone``),
            or an ISO-8601 timestamp (``time``, naive means UTC).
        timeout: Seconds to wait; clamped to the transport budget.
        pattern: Literal text (``file_text``) or regex (``regex``).
        poll_interval: Seconds between probes.
        expect_status: Exact HTTP status for ``http``; any 2xx/3xx when
            omitted.

    Returns:
        ``{"kind", "target", "met", "timed_out", "unreachable", "observed",
        "polls", "elapsed", "timeout", "timeout_requested", "clamped"}``.
        ``unreachable`` ends the wait early on a probe that cannot
        succeed; ``timed_out`` is then false.
    """
    problem = _validate(
        kind=kind,
        target=target,
        pattern=pattern,
        timeout=timeout,
        poll_interval=poll_interval,
    )
    if problem:
        return err(problem)
    compiled: re.Pattern[str] | None = None
    if kind == "regex":
        try:
            compiled = re.compile(pattern or "", re.MULTILINE)
        except re.error as exc:
            return err(f"invalid regex pattern: {exc}")

    budget = clamp_tool_timeout(timeout)
    interval = max(poll_interval, _MIN_POLL_INTERVAL)
    started = polling._clock()

    moment = _parse_moment(target=target) if kind == "time" else None
    if moment is not None:
        outcome = await _wait_for_time(moment=moment, timeout=budget.seconds)
    else:

        async def probe() -> Probe:
            return await _probe(
                kind=kind,
                target=target,
                pattern=pattern or "",
                compiled=compiled,
                expect_status=expect_status,
            )

        run = await polling.poll_until(
            probe=probe,
            done=lambda result: result.met or result.unreachable,
            deadline=polling.Deadline.after(seconds=budget.seconds),
            interval=interval,
        )
        outcome = {
            "met": run.last.met,
            "unreachable": run.last.unreachable,
            "observed": run.last.observed,
            "polls": run.polls,
        }

    return ok(
        {
            "kind": kind,
            "target": target,
            "met": outcome["met"],
            "timed_out": not outcome["met"] and not outcome["unreachable"],
            "unreachable": outcome["unreachable"],
            "observed": outcome["observed"],
            "polls": outcome["polls"],
            "elapsed": round(polling._clock() - started, 3),
            "timeout": budget.seconds,
            "timeout_requested": budget.requested,
            "clamped": budget.was_clamped,
        }
    )
