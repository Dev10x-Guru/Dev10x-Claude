"""Lossless writes to a vault's shared index and log notes (GH-1822).

Retro and pattern notes are new files with unique names, so two sessions
reflecting at once never collide on them. A folder's ``index.md`` and
``log.md`` are different: every reflection that touches the folder edits
them, and an unlocked read-modify-write from two sessions drops whichever
line was written first.

Every write here takes an exclusive lock, re-reads the note under the
lock, changes it, and replaces it atomically. The lock sidecar lives under
the Dev10x config directory, not beside the note, so the vault (often a
synced folder) never fills with ``.lock`` files. Writes are idempotent: a
line already present is reported as ``unchanged``, so a retried reflection
does not duplicate entries.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

from dev10x.domain.common.result import Result, SuccessResult, err, ok
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.file_locks import LockTimeoutError, atomic_write_text, file_lock
from dev10x.tasks.reflect.vault_config import VaultConfig, confine

log = logging.getLogger(__name__)

_DAY_HEADING = re.compile(r"^## (\d{4}-\d{2}-\d{2})\s*$")


class NoteAction(StrEnum):
    CREATED = "created"
    APPENDED = "appended"
    UNCHANGED = "unchanged"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class NoteWrite:
    path: Path
    action: NoteAction
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"path": str(self.path), "action": self.action.value, "reason": self.reason}


def _lock_target(note: Path) -> Path:
    digest = hashlib.sha256(str(note.resolve()).encode("utf-8")).hexdigest()[:24]
    return Dev10xConfigDir.reflect_locks_dir() / digest


def _note_path(*, config: VaultConfig, folder: str, name: str) -> Result[Path]:
    if not config.configured or config.vault is None:
        return err(config.reason or "no knowledge vault configured")
    directory = confine(vault=config.vault, relative=folder)
    if not isinstance(directory, SuccessResult):
        return directory
    return ok(directory.value / name)


def _normalize(line: str) -> str:
    return line.strip()


def _is_multiline(value: str) -> bool:
    """A value spanning lines defeats per-line idempotency and can forge a heading."""
    return len(value.strip().splitlines()) > 1


def _listing(directory: Path, *, exclude: set[str]) -> list[str]:
    if not directory.is_dir():
        return []
    notes = sorted(
        path.stem for path in directory.glob("*.md") if path.is_file() and path.name not in exclude
    )
    return [f"- [[{stem}]]" for stem in notes]


def add_index_line(
    *,
    config: VaultConfig,
    folder: str,
    line: str,
    seed_listing: bool = False,
) -> Result[NoteWrite]:
    """Add ``line`` to ``<folder>/<index_note>`` unless it is already there.

    A missing index is created with a title. With ``seed_listing`` the new
    index also lists every note already in the folder, so the folder hub
    is complete from its first write rather than only naming the newest
    note.
    """
    if not line.strip():
        return err("index line must not be empty")
    if _is_multiline(line):
        return err("index line must be a single line")
    note = _note_path(config=config, folder=folder, name=config.index_note)
    if not isinstance(note, SuccessResult):
        return note
    path = note.value
    entry = line.rstrip()
    try:
        with file_lock(_lock_target(path)):
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                existing = {_normalize(item) for item in text.splitlines()}
                if _normalize(entry) in existing:
                    return ok(NoteWrite(path=path, action=NoteAction.UNCHANGED))
                body = text if text.endswith("\n") or not text else text + "\n"
                atomic_write_text(path, body + entry + "\n")
                return ok(NoteWrite(path=path, action=NoteAction.APPENDED))
            lines = [f"# {path.parent.name or 'Index'}", ""]
            if seed_listing:
                excluded = {config.index_note, config.log_note}
                lines.extend(
                    item
                    for item in _listing(path.parent, exclude=excluded)
                    if item != _normalize(entry)
                )
            lines.append(entry)
            atomic_write_text(path, "\n".join(lines) + "\n")
            return ok(NoteWrite(path=path, action=NoteAction.CREATED))
    except LockTimeoutError as exc:
        return err(str(exc), path=str(path))
    except OSError as exc:
        log.error("index write failed", extra={"path": str(path), "error": str(exc)})
        return err(f"cannot write {path}: {exc}", path=str(path))


def _insert_log_entry(*, text: str, day: str, bullet: str) -> str | None:
    """Return ``text`` with ``bullet`` under ``## <day>``, newest day first.

    ``None`` means the bullet is already under that day's heading.
    """
    lines = text.splitlines()
    heading = f"## {day}"
    for index, current in enumerate(lines):
        if current.strip() != heading:
            continue
        end = index + 1
        while end < len(lines) and not _DAY_HEADING.match(lines[end]):
            if lines[end].strip() == bullet:
                return None
            end += 1
        insert_at = index + 1
        while insert_at < end and lines[insert_at].strip().startswith("- "):
            insert_at += 1
        lines.insert(insert_at, bullet)
        return "\n".join(lines) + "\n"

    older_day = next((i for i, current in enumerate(lines) if _is_older_day(current, day)), None)
    if older_day is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([heading, bullet])
    else:
        lines[older_day:older_day] = [heading, bullet, ""]
    return "\n".join(lines) + "\n"


def _is_older_day(line: str, day: str) -> bool:
    match = _DAY_HEADING.match(line)
    return match is not None and match.group(1) < day


def add_log_entry(
    *,
    config: VaultConfig,
    folder: str,
    entry: str,
    day: date,
    create: bool = False,
) -> Result[NoteWrite]:
    """Add ``- <entry>`` under today's ``## YYYY-MM-DD`` heading in the log.

    A folder without a log note is skipped unless ``create`` is set: not
    every folder keeps a log, and inventing one where the vault owner
    chose not to would clutter it.
    """
    if not entry.strip():
        return err("log entry must not be empty")
    if _is_multiline(entry):
        return err("log entry must be a single line")
    note = _note_path(config=config, folder=folder, name=config.log_note)
    if not isinstance(note, SuccessResult):
        return note
    path = note.value
    bullet = f"- {entry.strip().removeprefix('- ')}"
    try:
        with file_lock(_lock_target(path)):
            if not path.is_file():
                if not create:
                    return ok(
                        NoteWrite(
                            path=path,
                            action=NoteAction.SKIPPED,
                            reason="folder keeps no log note (pass --create to start one)",
                        )
                    )
                text = f"# {path.parent.name or 'Log'}\n"
                action = NoteAction.CREATED
            else:
                text = path.read_text(encoding="utf-8")
                action = NoteAction.APPENDED
            updated = _insert_log_entry(text=text, day=day.isoformat(), bullet=bullet)
            if updated is None:
                return ok(NoteWrite(path=path, action=NoteAction.UNCHANGED))
            atomic_write_text(path, updated)
            return ok(NoteWrite(path=path, action=action))
    except LockTimeoutError as exc:
        return err(str(exc), path=str(path))
    except OSError as exc:
        log.error("log write failed", extra={"path": str(path), "error": str(exc)})
        return err(f"cannot write {path}: {exc}", path=str(path))
