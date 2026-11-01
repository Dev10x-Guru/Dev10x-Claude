from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from dev10x.domain.claude_paths import ClaudeDir

STORE_PREFIX = "session-"
STORE_ID_CHARS = 8
STATUS_ORDER = {"in_progress": 0, "pending": 1, "completed": 2}


@dataclass(frozen=True)
class SessionTask:
    id: str
    subject: str
    status: str
    active_form: str = ""


def task_store(*, session_id: str, tasks_root: Path | None = None) -> Path:
    root = tasks_root if tasks_root is not None else ClaudeDir.home() / "tasks"
    return root / f"{STORE_PREFIX}{session_id[:STORE_ID_CHARS]}"


def _number(*, task_id: str) -> int:
    return int(task_id) if task_id.isdigit() else 0


def read_session_tasks(*, session_id: str, tasks_root: Path | None = None) -> list[SessionTask]:
    store = task_store(session_id=session_id, tasks_root=tasks_root)
    tasks = []
    for path in store.glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict) or not record.get("subject"):
            continue
        tasks.append(
            SessionTask(
                id=str(record.get("id", path.stem)),
                subject=str(record["subject"]),
                status=str(record.get("status", "pending")),
                active_form=str(record.get("activeForm", "")),
            )
        )
    return sorted(
        tasks,
        key=lambda task: (STATUS_ORDER.get(task.status, 1), _number(task_id=task.id)),
    )
