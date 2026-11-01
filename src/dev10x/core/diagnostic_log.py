"""Structured diagnostic log for the MCP server and skill commands (GH-1639).

Domain modules log through stdlib ``logging`` (script-domain-boundaries.md),
but nothing configured a sink: MCP-server and skill diagnostics went
wherever the host process happened to send stderr, which for the
long-lived MCP daemon is nowhere a person can read afterwards.

Decisions (GH-1639, 2026-11-01):

- **Destination** ``/tmp/Dev10x/log/`` beside the hook audit JSONL in
  ``/tmp/Dev10x/logs``. Volatile by choice: a restart clears it, which is
  the retention policy. ``DEV10X_DIAGNOSTIC_LOG_DIR`` overrides it.
- **Scope** the MCP server and ``dev10x skill`` commands. Hooks keep their
  own audit JSONL; adding a sink to them would cost latency on every tool
  call under the startup benchmark gate.
- **Schema** one JSON object per line, sharing ``ts`` and ``error_type``
  with the audit records so one reader serves both.
- **Privacy** every message and structured field is redacted at the sink
  by ``domain.log_redaction``, and the directory is a 0700 directory of
  this user's — a symlink or another user's directory is refused.

Writes go through ``atomic_append_line``: the daemon and several skill
processes append to the same daily file concurrently.
"""

from __future__ import annotations

import json
import logging
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dev10x.domain.file_locks import atomic_append_line
from dev10x.domain.log_redaction import redact_fields, redact_text

LOG_DIR_ENV = "DEV10X_DIAGNOSTIC_LOG_DIR"
DEFAULT_LOG_DIR = "/tmp/Dev10x/log"
LOGGER_NAME = "dev10x"

# LogRecord attributes that are plumbing, not caller-supplied context.
_STANDARD_ATTRS = frozenset(vars(logging.makeLogRecord({})).keys() | {"message", "asctime"})


def log_dir() -> Path:
    return Path(os.environ.get(LOG_DIR_ENV, DEFAULT_LOG_DIR))


class UnsafeLogDirError(OSError):
    """The log directory is not one this user alone controls."""


def ensure_private_dir(*, directory: Path) -> None:
    """Make ``directory`` a 0700 directory owned by this user, or refuse.

    ``/tmp`` is shared: another local user could pre-create the path, or
    a symlink at it, and receive every record. A directory that is not a
    real directory of ours is refused rather than repaired.
    """
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = os.lstat(directory)
    if not stat.S_ISDIR(info.st_mode):
        raise UnsafeLogDirError(f"{directory} is not a directory (symlink or file)")
    if info.st_uid != os.getuid():
        raise UnsafeLogDirError(f"{directory} is owned by uid {info.st_uid}, not this user")
    if stat.S_IMODE(info.st_mode) & 0o077:
        directory.chmod(0o700)


class JsonlDiagnosticHandler(logging.Handler):
    def __init__(self, *, component: str, directory: Path) -> None:
        super().__init__(level=logging.INFO)
        self.component = component
        self.directory = directory
        self._directory_checked = False
        self._refused = False

    def path_for(self, *, moment: datetime) -> Path:
        return self.directory / f"{self.component}-{moment:%Y-%m-%d}.jsonl"

    def build_record(self, *, record: logging.LogRecord) -> dict[str, Any]:
        moment = datetime.fromtimestamp(record.created, tz=UTC)
        payload: dict[str, Any] = {
            "ts": moment.isoformat(),
            "level": record.levelname,
            "component": self.component,
            "logger": record.name,
            "message": redact_text(text=record.getMessage()),
        }
        if record.exc_info and record.exc_info[0] is not None:
            payload["error_type"] = record.exc_info[0].__name__
        fields = {k: v for k, v in vars(record).items() if k not in _STANDARD_ATTRS}
        if fields:
            payload["fields"] = redact_fields(fields=fields)
        return payload

    def emit(self, record: logging.LogRecord) -> None:
        # A refused directory stays refused: retrying would repeat the
        # mkdir/lstat and print a traceback for every record in a daemon.
        if self._refused:
            return
        try:
            payload = self.build_record(record=record)
            if not self._directory_checked:
                try:
                    ensure_private_dir(directory=self.directory)
                except UnsafeLogDirError:
                    self._refused = True
                    raise
                self._directory_checked = True
            moment = datetime.fromtimestamp(record.created, tz=UTC)
            atomic_append_line(
                path=self.path_for(moment=moment),
                line=json.dumps(payload, default=str, ensure_ascii=False),
            )
        except Exception:
            self.handleError(record)


class StderrFallbackHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """WARNING and above on stderr, as ``logging.lastResort`` used to do.

    ``lastResort`` only fires when a logger hierarchy has no handler at
    all, so attaching the JSONL sink would otherwise silence every
    ``dev10x`` warning the MCP server and skill commands printed before.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setLevel(logging.WARNING)


def configure_diagnostic_log(*, component: str) -> JsonlDiagnosticHandler:
    """Attach the JSONL sink to the ``dev10x`` logger, once per component.

    Idempotent, so a skill command invoked inside an already-configured
    process does not double every line.
    """
    logger = logging.getLogger(LOGGER_NAME)
    if not any(isinstance(h, StderrFallbackHandler) for h in logger.handlers):
        logger.addHandler(StderrFallbackHandler())
    for handler in logger.handlers:
        if isinstance(handler, JsonlDiagnosticHandler) and handler.component == component:
            return handler
    handler = JsonlDiagnosticHandler(component=component, directory=log_dir())
    logger.addHandler(handler)
    if logger.level == logging.NOTSET or logger.level > logging.INFO:
        logger.setLevel(logging.INFO)
    return handler
