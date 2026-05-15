"""Plan domain class — typed wrapper for task plan YAML data.

Replaces the raw dict[str, Any] threading in task_plan_sync.py
with a cohesive domain object that owns its own persistence and
mutation logic.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _get_branch() -> str:
    from dev10x.domain.git_context import GitContext

    return GitContext().branch


def _extract_task_id(tool_result: str) -> str | None:
    match = re.search(r"Task #(\d+)", tool_result)
    return match.group(1) if match else None


def get_toplevel() -> str | None:
    """Return the git toplevel for the current CWD, or None outside a repo.

    A fresh GitContext is constructed per call so the MCP server (a
    long-lived process) sees the caller's effective CWD on every
    invocation instead of caching the directory the first call hit.
    """
    from dev10x.domain.git_context import GitContext

    return GitContext().toplevel


def get_plan_path(*, toplevel: str) -> Path:
    """Resolve the canonical plan file path within a git toplevel."""
    return Path(toplevel) / ".claude" / "session" / "plan.yaml"


class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    DELETED = "deleted"


@dataclass(frozen=True)
class TaskTransition:
    timestamp_field: str | None
    allowed_from: frozenset[TaskStatus | None]


# Declarative transition table. `allowed_from` lists the prior statuses
# that may transition to the target; `None` represents an absent/new
# status (the task entry has no `status` field yet). DELETED is reachable
# from any state because the operation removes the task entirely.
TASK_TRANSITIONS: dict[TaskStatus, TaskTransition] = {
    TaskStatus.PENDING: TaskTransition(
        timestamp_field=None,
        allowed_from=frozenset({None, TaskStatus.PENDING, TaskStatus.IN_PROGRESS}),
    ),
    TaskStatus.IN_PROGRESS: TaskTransition(
        timestamp_field="started_at",
        allowed_from=frozenset({None, TaskStatus.PENDING, TaskStatus.IN_PROGRESS}),
    ),
    TaskStatus.COMPLETED: TaskTransition(
        timestamp_field="completed_at",
        allowed_from=frozenset(
            {
                None,
                TaskStatus.PENDING,
                TaskStatus.IN_PROGRESS,
                TaskStatus.COMPLETED,
            }
        ),
    ),
    TaskStatus.DELETED: TaskTransition(
        timestamp_field=None,
        allowed_from=frozenset(
            {
                None,
                TaskStatus.PENDING,
                TaskStatus.IN_PROGRESS,
                TaskStatus.COMPLETED,
                TaskStatus.DELETED,
            }
        ),
    ),
}


@dataclass
class Plan:
    metadata: dict[str, Any] = field(default_factory=dict)
    tasks: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, *, path: Path) -> Plan:
        if path.exists():
            try:
                with open(path) as f:
                    data = yaml.safe_load(f) or {}
            except (yaml.YAMLError, OSError):
                data = {}
        else:
            data = {}
        return cls(
            metadata=data.get("plan", {}),
            tasks=data.get("tasks", []),
        )

    def save(self, *, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        plan_data = self._to_dict()
        fd, tmp_path = tempfile.mkstemp(
            dir=str(path.parent),
            prefix=".plan-",
            suffix=".yaml.tmp",
        )
        try:
            with os.fdopen(fd, "w") as f:
                yaml.dump(
                    plan_data,
                    f,
                    default_flow_style=False,
                    sort_keys=False,
                    allow_unicode=True,
                )
            os.rename(tmp_path, str(path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self.metadata:
            result["plan"] = self.metadata
        if self.tasks:
            result["tasks"] = self.tasks
        return result

    def archive(self, *, path: Path) -> None:
        """Stamp `archived_at` on plan metadata and persist to `path`."""
        self.metadata["archived_at"] = _now_iso()
        self.save(path=path)

    def ensure_metadata(self) -> None:
        if not self.metadata:
            self.metadata = {
                "created_at": _now_iso(),
                "branch": _get_branch(),
                "status": "in_progress",
            }
        self.metadata["last_synced"] = _now_iso()

    @property
    def is_new(self) -> bool:
        return not self.metadata

    def context_keys(self) -> list[str]:
        """Return the top-level keys stored under plan context."""
        context = self.metadata.get("context", {})
        if not isinstance(context, dict):
            return []
        return list(context.keys())

    def handle_task_create(
        self,
        *,
        tool_input: dict[str, Any],
        tool_result: str,
    ) -> bool:
        task_id = _extract_task_id(tool_result)
        if not task_id:
            return False

        task_entry: dict[str, Any] = {
            "id": task_id,
            "subject": tool_input.get("subject", ""),
            "status": TaskStatus.PENDING.value,
            "created_at": _now_iso(),
        }
        description = tool_input.get("description")
        if description:
            task_entry["description"] = description
        metadata = tool_input.get("metadata")
        if metadata:
            task_entry["metadata"] = metadata

        existing_ids = {t.get("id") for t in self.tasks}
        if task_id not in existing_ids:
            self.tasks.append(task_entry)
            return True
        return False

    def handle_task_update(self, *, tool_input: dict[str, Any]) -> None:
        task_id = tool_input.get("taskId")
        if not task_id:
            return

        raw_status = tool_input.get("status")
        target_status = _coerce_status(raw_status)
        if target_status is TaskStatus.DELETED:
            self.tasks = [t for t in self.tasks if t.get("id") != task_id]
            return

        for task in self.tasks:
            if task.get("id") != task_id:
                continue
            if target_status is not None and not _is_valid_transition(
                current=_coerce_status(task.get("status")),
                target=target_status,
            ):
                # Reject invalid transitions silently; the hook must keep
                # processing other updates rather than crashing on a stale
                # status flip caused by clock skew or replay.
                break
            if target_status is not None:
                task["status"] = target_status.value
                transition = TASK_TRANSITIONS[target_status]
                if transition.timestamp_field is not None:
                    task[transition.timestamp_field] = _now_iso()
            if "subject" in tool_input:
                task["subject"] = tool_input["subject"]
            if "description" in tool_input:
                task["description"] = tool_input["description"]
            if "metadata" in tool_input:
                existing_meta = task.get("metadata", {})
                for k, v in tool_input["metadata"].items():
                    if v is None:
                        existing_meta.pop(k, None)
                    else:
                        existing_meta[k] = v
                if existing_meta:
                    task["metadata"] = existing_meta
            break

    def check_all_completed(self) -> None:
        all_statuses = [t.get("status") for t in self.tasks]
        if all_statuses and all(s == TaskStatus.COMPLETED.value for s in all_statuses):
            self.metadata["status"] = TaskStatus.COMPLETED.value
            self.metadata["completed_at"] = _now_iso()

    def set_context(self, *, key: str, value: str) -> None:
        context = self.metadata.setdefault("context", {})
        _set_nested(d=context, dotpath=key, value=value)


def _coerce_status(raw: Any) -> TaskStatus | None:
    if raw is None:
        return None
    try:
        return TaskStatus(raw)
    except ValueError:
        return None


def _is_valid_transition(
    *,
    current: TaskStatus | None,
    target: TaskStatus,
) -> bool:
    return current in TASK_TRANSITIONS[target].allowed_from


def _set_nested(*, d: dict[str, Any], dotpath: str, value: str) -> None:
    keys = dotpath.split(".")
    for key in keys[:-1]:
        d = d.setdefault(key, {})
    try:
        d[keys[-1]] = json.loads(value)
    except (json.JSONDecodeError, ValueError):
        d[keys[-1]] = value
