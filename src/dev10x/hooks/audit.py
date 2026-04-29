"""Per-hook execution timing and outcome telemetry (GH-860).

Two-layer observability:

  Outer wrapper (hooks/scripts/audit-wrap, POSIX shell) — captures
  wall-clock `total_ms` around the full hook invocation, including
  `uv run` or `/usr/bin/env` startup, Python interpreter import, and
  module load. Emits a `phase: "wrap"` record.

  Inner decorator (@audit_hook) — captures `body_ms` after imports
  complete, reads the wrapper-provided span id via
  DEV10X_HOOK_SPAN_ID, and emits a `phase: "body"` record with
  matching span id. The two records join via span id so derived
  `startup_ms = total_ms - body_ms` becomes an obvious signal.

Records land at DEV10X_HOOK_AUDIT_DIR/hooks-YYYY-MM-DD.jsonl.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import Any, TypeVar

SPAN_ID_ENV = "DEV10X_HOOK_SPAN_ID"
AUDIT_ENABLE_ENV = "DEV10X_HOOK_AUDIT"
AUDIT_DIR_ENV = "DEV10X_HOOK_AUDIT_DIR"
AUDIT_RETAIN_ENV = "DEV10X_HOOK_AUDIT_RETAIN_DAYS"

DEFAULT_AUDIT_DIR = "/tmp/Dev10x/logs"
DEFAULT_RETAIN_DAYS = 30

F = TypeVar("F", bound=Callable[..., Any])


def _audit_enabled() -> bool:
    raw = os.environ.get(AUDIT_ENABLE_ENV, "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _audit_dir() -> Path:
    return Path(os.environ.get(AUDIT_DIR_ENV, DEFAULT_AUDIT_DIR))


def _log_path(*, now: datetime | None = None) -> Path:
    ts = now or datetime.now(UTC)
    return _audit_dir() / f"hooks-{ts.strftime('%Y-%m-%d')}.jsonl"


def _new_span_id() -> str:
    return uuid.uuid4().hex[:16]


def _current_span_id() -> str:
    return os.environ.get(SPAN_ID_ENV, "") or _new_span_id()


def _write_record(*, record: dict[str, Any]) -> None:
    """Append a JSONL record. Failures never propagate to the hook body."""
    try:
        log_dir = _audit_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        path = _log_path()
        line = json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n"
        with path.open("a") as f:
            f.write(line)
    except OSError:
        pass


def _classify_outcome(*, exit_code: int) -> str:
    if exit_code == 0:
        return "ok"
    if exit_code == 2:
        return "block"
    if exit_code == 1:
        return "error"
    return "unknown"


def audit_hook(name: str, *, event: str = "") -> Callable[[F], F]:
    """Decorator: record a body-phase audit entry around the hook function.

    Args:
        name: stable hook identifier (e.g., "validate-bash", "session-reload")
        event: Claude Code event name (e.g., "PreToolUse", "SessionStart")

    The wrapped function may call sys.exit(); the decorator intercepts
    SystemExit so the audit record is written before the process dies.
    Any other exception is re-raised after the record is written.
    """

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not _audit_enabled():
                return func(*args, **kwargs)

            span_id = _current_span_id()
            session_id = ""
            start = time.perf_counter()
            exit_code = 0
            error: BaseException | None = None

            try:
                return func(*args, **kwargs)
            except SystemExit as exc:
                code = exc.code
                if isinstance(code, int):
                    exit_code = code
                elif code is None:
                    exit_code = 0
                else:
                    exit_code = 1
                error = exc
                raise
            except BaseException as exc:
                exit_code = 1
                error = exc
                raise
            finally:
                body_ms = int((time.perf_counter() - start) * 1000)
                record = {
                    "phase": "body",
                    "ts": datetime.now(UTC).isoformat(),
                    "hook": name,
                    "event": event,
                    "span_id": span_id,
                    "session_id": session_id,
                    "body_ms": body_ms,
                    "outcome": _classify_outcome(exit_code=exit_code),
                }
                if error is not None and not isinstance(error, SystemExit):
                    record["error_type"] = type(error).__name__
                _write_record(record=record)

        return wrapper  # type: ignore[return-value]

    return decorator


def write_wrap_record(
    *,
    hook: str,
    argv: list[str],
    total_ms: int,
    exit_code: int,
    span_id: str,
) -> None:
    """Write a wrapper-phase record. Called by the audit-wrap shell script
    via `dev10x hook audit wrap-record` — or directly by Python tooling
    for testing.
    """
    if not _audit_enabled():
        return
    record = {
        "phase": "wrap",
        "ts": datetime.now(UTC).isoformat(),
        "hook": hook,
        "argv": argv,
        "span_id": span_id,
        "total_ms": total_ms,
        "exit_code": exit_code,
        "outcome": _classify_outcome(exit_code=exit_code),
    }
    _write_record(record=record)


def iter_records(*, since: datetime | None = None) -> list[dict[str, Any]]:
    """Read recent audit records across log files within retention window."""
    log_dir = _audit_dir()
    if not log_dir.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(log_dir.glob("hooks-*.jsonl")):
        try:
            with path.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if since is not None:
                        ts_raw = rec.get("ts", "")
                        try:
                            ts = datetime.fromisoformat(ts_raw)
                        except ValueError:
                            continue
                        if ts < since:
                            continue
                    records.append(rec)
        except OSError:
            continue
    return records


def summarize(*, records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Aggregate records by hook name. Joins wrap+body via span_id when
    both records are present.

    Returns a mapping of `hook` → aggregated stats:
        count, total_ms_avg, body_ms_avg, startup_ms_avg,
        error_count, block_count
    """
    by_span: dict[str, dict[str, Any]] = {}
    body_only: list[dict[str, Any]] = []
    wrap_only: list[dict[str, Any]] = []

    for rec in records:
        phase = rec.get("phase")
        span_id = rec.get("span_id", "")
        if not span_id:
            if phase == "body":
                body_only.append(rec)
            elif phase == "wrap":
                wrap_only.append(rec)
            continue
        if not isinstance(phase, str):
            continue
        bucket = by_span.setdefault(span_id, {})
        bucket[phase] = rec

    hook_stats: dict[str, dict[str, Any]] = {}
    for span in by_span.values():
        body = span.get("body")
        wrap = span.get("wrap")
        record = body or wrap
        if record is None:
            continue
        hook = record.get("hook", "unknown")
        stats = hook_stats.setdefault(
            hook,
            {
                "count": 0,
                "total_ms_sum": 0,
                "body_ms_sum": 0,
                "startup_ms_sum": 0,
                "paired_count": 0,
                "error_count": 0,
                "block_count": 0,
            },
        )
        stats["count"] += 1
        outcome = record.get("outcome", "")
        if outcome == "error":
            stats["error_count"] += 1
        elif outcome == "block":
            stats["block_count"] += 1
        if body and wrap:
            total = int(wrap.get("total_ms") or 0)
            body_ms = int(body.get("body_ms") or 0)
            stats["total_ms_sum"] += total
            stats["body_ms_sum"] += body_ms
            stats["startup_ms_sum"] += max(total - body_ms, 0)
            stats["paired_count"] += 1

    for stats in hook_stats.values():
        paired = stats["paired_count"] or 1
        stats["total_ms_avg"] = round(stats["total_ms_sum"] / paired, 1)
        stats["body_ms_avg"] = round(stats["body_ms_sum"] / paired, 1)
        stats["startup_ms_avg"] = round(stats["startup_ms_sum"] / paired, 1)

    return hook_stats


def prune(*, retain_days: int | None = None) -> int:
    """Remove log files older than retain_days. Returns count deleted."""
    days = retain_days
    if days is None:
        raw = os.environ.get(AUDIT_RETAIN_ENV, str(DEFAULT_RETAIN_DAYS))
        try:
            days = int(raw)
        except ValueError:
            days = DEFAULT_RETAIN_DAYS
    cutoff = time.time() - days * 86400
    log_dir = _audit_dir()
    if not log_dir.exists():
        return 0
    deleted = 0
    for path in log_dir.glob("hooks-*.jsonl"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                deleted += 1
        except OSError:
            pass
    return deleted


def new_wrap_context() -> tuple[str, float]:
    """Called by the wrapper (via CLI shim) to mint a span id and
    record the start time. Returns (span_id, start_perf_counter).
    """
    return _new_span_id(), time.perf_counter()


def finish_wrap_context(
    *,
    hook: str,
    argv: list[str],
    span_id: str,
    start: float,
    exit_code: int,
) -> None:
    total_ms = int((time.perf_counter() - start) * 1000)
    write_wrap_record(
        hook=hook,
        argv=argv,
        total_ms=total_ms,
        exit_code=exit_code,
        span_id=span_id,
    )


def cli_wrap_record(argv: list[str] | None = None) -> None:
    """CLI entry point: `dev10x hook audit wrap-record <hook> <span_id>
    <total_ms> <exit_code> [argv...]`

    Called by hooks/scripts/audit-wrap after the child process exits.
    """
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) < 4:
        sys.exit(0)
    hook = argv[0]
    span_id = argv[1]
    try:
        total_ms = int(argv[2])
        exit_code = int(argv[3])
    except ValueError:
        sys.exit(0)
    child_argv = argv[4:]
    write_wrap_record(
        hook=hook,
        argv=child_argv,
        total_ms=total_ms,
        exit_code=exit_code,
        span_id=span_id,
    )
