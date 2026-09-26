"""Timestamped backup and restore for settings JSON files (Memento pattern).

Creates `.bak.<timestamp>` files adjacent to originals before bulk
modifications.  Supports restoring the most recent backup per file
or all backups in a single pass. :func:`create_backup` is the
Originator's snapshot step and :func:`restore_backup` /
:func:`restore_all` the Caretaker's rollback — the classic GoF
Memento shape applied to a settings file instead of an in-memory
object.

:func:`backed_up_write` (GH-1429) is the structural counterpart:
thirteen call sites across this package repeated the identical
`create_backup(path); with locked_json_update(path=path) as
live_data: ...`, guarded by a caller-side `if not dry_run:`, as a
copy-pasted idiom with no shared abstraction enforcing "always back
up before a locked write". This context manager owns that whole
idiom — the backup step, the dry-run short-circuit, and the locked
read-modify-write — so a new mutator cannot omit the backup by
forgetting to copy the right three lines.
"""

from __future__ import annotations

import shutil
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dev10x.skills.permission.file_lock import locked_json_update

BACKUP_SUFFIX_PREFIX = ".bak."
TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"


def create_backup(path: Path) -> Path | None:
    if not path.is_file():
        return None
    ts = datetime.now(tz=UTC).strftime(TIMESTAMP_FORMAT)
    backup_path = path.with_name(f"{path.name}{BACKUP_SUFFIX_PREFIX}{ts}")
    shutil.copy2(path, backup_path)
    return backup_path


def find_backups(path: Path) -> list[Path]:
    pattern = f"{path.name}{BACKUP_SUFFIX_PREFIX}*"
    return sorted(path.parent.glob(pattern))


def find_latest_backup(path: Path) -> Path | None:
    backups = find_backups(path)
    return backups[-1] if backups else None


def restore_backup(
    path: Path,
    *,
    backup: Path | None = None,
) -> Path | None:
    target = backup or find_latest_backup(path)
    if target is None or not target.is_file():
        return None
    shutil.copy2(target, path)
    return target


def restore_all(paths: list[Path]) -> list[tuple[Path, Path]]:
    restored: list[tuple[Path, Path]] = []
    for path in paths:
        backup = find_latest_backup(path)
        if backup is not None:
            result = restore_backup(path, backup=backup)
            if result is not None:
                restored.append((path, result))
    return restored


def restore_report(*, paths: list[Path]) -> tuple[int, str]:
    """Restore the latest backup for each path and build a CLI report.

    Shared tail for the permission-skill ``_restore`` sub-commands
    (GH-583). Returns an ``(exit_code, message)`` pair so each entry
    point owns the actual ``print`` — keeping this reusable helper on
    the return-value side of the script/domain boundary (GH-246 H3).
    """
    restored = restore_all(paths=paths)
    if not restored:
        return 0, "No backups found to restore."
    lines = [f"  Restored {original} from {backup.name}" for original, backup in restored]
    lines.append(f"\nRestored {len(restored)} files.")
    return 0, "\n".join(lines)


@contextmanager
def backed_up_write(
    path: Path,
    *,
    dry_run: bool = False,
) -> Generator[dict[str, Any] | None, None, None]:
    """Back up ``path``, then hold its write lock — or no-op under ``dry_run``.

    Owns the whole "back up, then locked read-modify-write" idiom
    (GH-1429) rather than leaving each caller to copy-paste
    ``create_backup(path)`` followed by a ``locked_json_update``
    ``with`` block behind its own ``if not dry_run:`` guard. Folding
    the guard in here — rather than leaving it at each call site —
    is what makes the backup unskippable: a call site can no longer
    reach the write path without going through the backup step,
    because there is no other way to reach it.

    Recomputes the TOCTOU question the same way every call site should:
    the caller reads and mutates ``live_data`` — this run's live
    content under the lock — never a value it computed before the lock
    was acquired. ``canonicalize_settings_file`` in ``doctor.py``
    demonstrates the pattern (re-running its own transform against
    ``live_data``); a caller that instead extends ``live_data`` with a
    list computed outside this context manager has reintroduced the
    same race a fresh lock acquisition cannot fix on its own.

    Args:
        path: Settings file to back up and lock.
        dry_run: When True, skip both the backup and the lock entirely
            and yield ``None`` — the caller's ``with`` body MUST guard
            on ``if live_data is not None:`` before performing any
            write, matching the dry-run contract every migrated call
            site already followed via its own ``if not dry_run:``.

    Yields:
        The locked live JSON content as a dict, or ``None`` under
        ``dry_run=True``.
    """
    if dry_run:
        yield None
        return

    create_backup(path)
    with locked_json_update(path=path) as live_data:
        yield live_data
