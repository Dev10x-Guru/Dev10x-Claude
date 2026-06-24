"""Audit log retention/pruning (GH-530).

Removing log files past the retention window is a lifecycle concern,
distinct from reading/appending the JSONL event log (`log_reader`) and
from summarizing records (`summarizer`). It lived in `audit.log_reader`
only because that was the first home; this module owns it now so the
reader stays focused on log IO. The stable import path is
`dev10x.audit.prune` (re-exported from the package).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from dev10x.audit.log_reader import AUDIT_RETAIN_ENV, DEFAULT_RETAIN_DAYS, audit_dir


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
