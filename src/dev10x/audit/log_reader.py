"""Audit log reader and append API (GH-143).

Owns the JSONL audit log surface: path resolution, record iteration,
pruning, and the append API consumed by `dev10x.hooks.audit_emit`
(the write side). Record summarization lives in
`dev10x.audit.summarizer` (re-exported here for the legacy import path).

Two-layer observability:

  Outer wrapper (hooks/scripts/audit-wrap, POSIX shell) — captures
  wall-clock `total_ms` around the full hook invocation, including
  interpreter startup and module imports. Emits a `phase: "wrap"`
  record.

  Inner decorator (@audit_hook in `audit_emit`) — captures `body_ms`
  after imports complete, joins to the wrapper via a shared span id,
  and emits a `phase: "body"` record. Derived `startup_ms = total_ms
  - body_ms` exposes interpreter/import overhead.

Records land at DEV10X_HOOK_AUDIT_DIR/hooks-YYYY-MM-DD.jsonl.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dev10x.audit.summarizer import summarize  # noqa: F401  (re-export — audit finding D4)
from dev10x.domain.hook_telemetry import HookOutcome

SPAN_ID_ENV = "DEV10X_HOOK_SPAN_ID"
AUDIT_ENABLE_ENV = "DEV10X_HOOK_AUDIT"
AUDIT_DIR_ENV = "DEV10X_HOOK_AUDIT_DIR"
AUDIT_RETAIN_ENV = "DEV10X_HOOK_AUDIT_RETAIN_DAYS"

DEFAULT_AUDIT_DIR = "/tmp/Dev10x/logs"
DEFAULT_RETAIN_DAYS = 30


def audit_enabled() -> bool:
    raw = os.environ.get(AUDIT_ENABLE_ENV, "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


def audit_dir() -> Path:
    return Path(os.environ.get(AUDIT_DIR_ENV, DEFAULT_AUDIT_DIR))


def log_path(*, now: datetime | None = None, base_dir: Path | None = None) -> Path:
    ts = now or datetime.now(UTC)
    base = base_dir or audit_dir()
    return base / f"hooks-{ts.strftime('%Y-%m-%d')}.jsonl"


def new_span_id() -> str:
    return uuid.uuid4().hex[:16]


def current_span_id() -> str:
    return os.environ.get(SPAN_ID_ENV, "") or new_span_id()


def append_record(*, record: dict[str, Any], base_dir: Path | None = None) -> None:
    """Append a JSONL record. Failures never propagate to the caller.

    Uses ``os.open(O_APPEND|O_WRONLY|O_CREAT)`` + a single ``os.write``
    so concurrent hook processes do not interleave partial JSON lines.
    POSIX guarantees that a single ``write()`` call to an ``O_APPEND``
    fd is atomic up to ``PIPE_BUF`` bytes; audit records are well
    under that limit (typically < 512 bytes). ``TextIOWrapper.write``
    can split a single record into multiple syscalls under the hood,
    losing the append-atomicity guarantee.
    """
    try:
        log_dir = base_dir or audit_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_path(base_dir=log_dir)
        line = (json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
        fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    except OSError:
        pass


def classify_outcome(*, exit_code: int) -> HookOutcome:
    return HookOutcome.from_exit_code(exit_code)


def iter_records(
    *,
    since: datetime | None = None,
    base_dir: Path | None = None,
    paths: list[Path] | None = None,
) -> list[dict[str, Any]]:
    """Read recent audit records across log files within retention window.

    When `paths` is provided, only those files are scanned. Otherwise scan
    every `hooks-*.jsonl` under `base_dir` (defaulting to `audit_dir()`).
    """
    if paths is not None:
        scan_paths = sorted(paths)
    else:
        log_dir = base_dir or audit_dir()
        if not log_dir.exists():
            return []
        scan_paths = sorted(log_dir.glob("hooks-*.jsonl"))
    records: list[dict[str, Any]] = []
    for path in scan_paths:
        try:
            with path.open() as f:
                for raw_line in f:
                    line = raw_line.strip()
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


class LogReaderAuditWriter:
    """Concrete ``AuditWriter`` backed by this module's JSONL log surface.

    The audit memo I6 inversion (``hooks → audit``) is sealed by having
    ``hooks.audit_emit`` depend on ``domain.audit_writer.AuditWriter`` and
    receive this concrete adapter through one injection seam. Methods
    delegate to the module-level functions so the on-disk behaviour is
    unchanged.
    """

    def audit_enabled(self) -> bool:
        return audit_enabled()

    def append_record(self, *, record: dict[str, Any]) -> None:
        append_record(record=record)

    def new_span_id(self) -> str:
        return new_span_id()

    def current_span_id(self) -> str:
        return current_span_id()

    def classify_outcome(self, *, exit_code: int) -> HookOutcome:
        return classify_outcome(exit_code=exit_code)


def prune(*, retain_days: int | None = None, base_dir: Path | None = None) -> int:
    """Remove log files older than retain_days. Returns count deleted."""
    days = retain_days
    if days is None:
        raw = os.environ.get(AUDIT_RETAIN_ENV, str(DEFAULT_RETAIN_DAYS))
        try:
            days = int(raw)
        except ValueError:
            days = DEFAULT_RETAIN_DAYS
    cutoff = time.time() - days * 86400
    log_dir = base_dir or audit_dir()
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
