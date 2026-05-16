"""Hook audit emitters (write side) — decorator + wrap-record helpers.

Companion to `dev10x.audit.log_reader`. This module owns the
`@audit_hook` decorator wrapped around hook bodies and the
wrap-phase record helpers called by `hooks/scripts/audit-wrap`.
All writes flow through `log_reader.append_record` so the reader
remains the single source of truth for log layout.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from functools import wraps
from typing import Any, TypeVar

from dev10x.audit.log_reader import (
    append_record,
    audit_enabled,
    classify_outcome,
    current_span_id,
    new_span_id,
)
from dev10x.domain.hook_telemetry import HookPhase

F = TypeVar("F", bound=Callable[..., Any])


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
            if not audit_enabled():
                return func(*args, **kwargs)

            span_id = current_span_id()
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
                    "phase": HookPhase.BODY,
                    "ts": datetime.now(UTC).isoformat(),
                    "hook": name,
                    "event": event,
                    "span_id": span_id,
                    "session_id": session_id,
                    "body_ms": body_ms,
                    "outcome": classify_outcome(exit_code=exit_code),
                }
                if error is not None and not isinstance(error, SystemExit):
                    record["error_type"] = type(error).__name__
                append_record(record=record)

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
    if not audit_enabled():
        return
    record = {
        "phase": HookPhase.WRAP,
        "ts": datetime.now(UTC).isoformat(),
        "hook": hook,
        "argv": argv,
        "span_id": span_id,
        "total_ms": total_ms,
        "exit_code": exit_code,
        "outcome": classify_outcome(exit_code=exit_code),
    }
    append_record(record=record)


def new_wrap_context() -> tuple[str, float]:
    """Called by the wrapper (via CLI shim) to mint a span id and
    record the start time. Returns (span_id, start_perf_counter).
    """
    return new_span_id(), time.perf_counter()


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
