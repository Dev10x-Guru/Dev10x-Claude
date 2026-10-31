from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dev10x.core.domain.file_locks import atomic_append_line

OUTBOX_ENV: str = "DEV10X_CI_OUTBOX"


def append_entry(*, path: Path, entry: dict[str, Any]) -> None:
    stamped = {"ts": datetime.now(tz=UTC).isoformat(), **entry}
    atomic_append_line(path, json.dumps(stamped, ensure_ascii=False))


def read_entries(*, path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
