"""Timestamped backup and restore for settings JSON files.

Creates `.bak.<timestamp>` files adjacent to originals before bulk
modifications.  Supports restoring the most recent backup per file
or all backups in a single pass.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

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
