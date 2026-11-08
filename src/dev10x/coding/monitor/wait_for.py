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
import math
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dev10x.core.mcp.daemon import is_pid_alive
from dev10x.domain import polling
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
    met: bool
    observed: dict[str, Any]


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
        return Probe(met=False, observed=observed)
    if compiled is None:
        found = pattern in text
        observed["match"] = pattern if found else None
        return Probe(met=found, observed=observed)
    match = compiled.search(text)
    observed["match"] = match.group(0)[:_EXCERPT_CHARS] if match else None
    return Probe(met=match is not None, observed=observed)


def _http_status(*, url: str) -> tuple[int | None, str | None]:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=_PROBE_TIMEOUT_SECONDS) as response:  # noqa: S310
            return int(response.status), None
    except urllib.error.HTTPError as exc:
        return int(exc.code), None
    except (http.client.HTTPException, OSError, ValueError) as exc:
        return None, str(exc)[:_EXCERPT_CHARS]


async def _probe_http(*, target: str, expect_status: int | None) -> Probe:
    status, error = await asyncio.to_thread(_http_status, url=target)
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
        return Probe(met=False, observed={"pattern": target, "error": f"pgrep unavailable: {exc}"})
    if result.returncode not in (0, 1):
        return Probe(
            met=False,
            observed={"pattern": target, "error": (result.stderr or "pgrep failed").strip()},
        )
    pids = [int(line) for line in result.stdout.split() if line.isdigit()]
    return Probe(met=not pids, observed={"pattern": target, "pids": pids})


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
    if kind == "http" and not target.startswith(_HTTP_SCHEMES):
        return f"kind='http' needs an http(s) URL, got {target!r}"
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
        ``{"kind", "target", "met", "timed_out", "observed", "polls",
        "elapsed", "timeout", "timeout_requested", "clamped"}``.
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
            done=lambda result: result.met,
            deadline=polling.Deadline.after(seconds=budget.seconds),
            interval=interval,
        )
        outcome = {"met": run.last.met, "observed": run.last.observed, "polls": run.polls}

    return ok(
        {
            "kind": kind,
            "target": target,
            "met": outcome["met"],
            "timed_out": not outcome["met"],
            "observed": outcome["observed"],
            "polls": outcome["polls"],
            "elapsed": round(polling._clock() - started, 3),
            "timeout": budget.seconds,
            "timeout_requested": budget.requested,
            "clamped": budget.was_clamped,
        }
    )
