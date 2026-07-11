"""Plan domain class — typed wrapper for task plan YAML data.

Replaces the raw dict[str, Any] threading in task_plan_sync.py
with a cohesive domain object that owns its own persistence and
mutation logic. Tasks are typed `Task` value objects (GH-241
finding B1/B10) — load/save round-trip preserves all fields.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from dev10x.domain.documents.task import Task, TaskStatus
from dev10x.domain.file_locks import atomic_write_text

# Terminal-task invariant (GH-149 / GH-681). Owned here so the PreToolUse
# guard asks the Plan rather than re-deriving the rule externally
# (Tell-Don't-Ask).
_TERMINAL_SUBJECT = re.compile(r"verify\s+ac", re.IGNORECASE)
_OPEN_STATUSES = (TaskStatus.PENDING, TaskStatus.IN_PROGRESS)
_CLOSING_STATUSES = ("completed", "deleted")


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


@dataclass(frozen=True)
class TaskTransition:
    allowed_from: frozenset[TaskStatus | None]
    removes: bool = False


# Declarative transition table. `allowed_from` lists the prior statuses
# that may transition to the target; `None` represents an absent/new
# status (the task entry has no `status` field yet). DELETED is reachable
# from any state because the operation removes the task entirely.
TASK_TRANSITIONS: dict[TaskStatus, TaskTransition] = {
    TaskStatus.PENDING: TaskTransition(
        allowed_from=frozenset({None, TaskStatus.PENDING, TaskStatus.IN_PROGRESS}),
    ),
    TaskStatus.IN_PROGRESS: TaskTransition(
        allowed_from=frozenset({None, TaskStatus.PENDING, TaskStatus.IN_PROGRESS}),
    ),
    TaskStatus.COMPLETED: TaskTransition(
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
        allowed_from=frozenset(
            {
                None,
                TaskStatus.PENDING,
                TaskStatus.IN_PROGRESS,
                TaskStatus.COMPLETED,
                TaskStatus.DELETED,
            }
        ),
        removes=True,
    ),
}


@dataclass(frozen=True)
class TerminalTaskViolation:
    """Descriptor for a close that would break the terminal-task invariant.

    ``subject`` is the offending task's title; ``is_terminal`` distinguishes
    the terminal Verify-AC task from the merely-last open task so the caller
    can phrase its message. The Plan returns this instead of a bare bool so
    the guard owns presentation while the domain owns the rule.
    """

    subject: str
    is_terminal: bool


@dataclass
class Plan:
    """The mutable plan aggregate.

    Owns its own persistence (`load`/`save`), task state machine
    (`handle_task_*`, `TASK_TRANSITIONS`), and archive lifecycle
    (`stamp_archived`, `archive_filename`, `archive_to`). The
    `plan.service` layer wraps this aggregate with the IO/transaction
    concerns it must NOT own — git-toplevel resolution, file locking,
    and removing the live plan file.
    """

    metadata: dict[str, Any] = field(default_factory=dict)
    tasks: list[Task] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Accept raw dicts at construction so tests and legacy callers
        # that pass `tasks=[{"id": ...}]` keep working — normalize to
        # `Task` instances eagerly.
        normalized: list[Task] = []
        for item in self.tasks:
            if isinstance(item, Task):
                normalized.append(item)
            elif isinstance(item, dict):
                normalized.append(Task.from_dict(item))
        self.tasks = normalized

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
        raw_tasks = data.get("tasks", []) or []
        tasks = [Task.from_dict(t) for t in raw_tasks if isinstance(t, dict)]
        return cls(
            metadata=data.get("plan", {}),
            tasks=tasks,
        )

    def save(self, *, path: Path) -> None:
        content = yaml.dump(
            self.to_dict(),
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
        atomic_write_text(path, content)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self.metadata:
            result["plan"] = self.metadata
        if self.tasks:
            result["tasks"] = [t.to_dict() for t in self.tasks]
        return result

    def stamp_archived(self) -> None:
        """Record the `archived_at` timestamp on plan metadata.

        Mutation only — does not persist. Callers pair this with
        `save()` (see `archive`/`archive_to`).
        """
        self.metadata["archived_at"] = _now_iso()

    def archive_filename(self, *, timestamp: str) -> str:
        """Derive the archive filename for this plan at `timestamp`.

        The branch slug is sanitised (slashes → hyphens, capped at 50
        chars) so the name is filesystem-safe regardless of branch
        naming convention.
        """
        branch_slug = self.metadata.get("branch", "unknown")
        branch_slug = branch_slug.replace("/", "-")[:50]
        return f"plan-{timestamp}-{branch_slug}.yaml"

    def archive(self, *, path: Path) -> None:
        """Stamp `archived_at` on plan metadata and persist to `path`."""
        self.stamp_archived()
        self.save(path=path)

    def archive_to(self, *, archive_dir: Path, timestamp: str) -> Path:
        """Stamp, persist under `archive_dir`, and return the archive path.

        Encapsulates name derivation and the `archived_at` stamp so the
        service layer only owns IO orchestration (toplevel resolution,
        file locking, removing the live plan file). `archive_dir` is
        created if absent.
        """
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = archive_dir / self.archive_filename(timestamp=timestamp)
        self.stamp_archived()
        self.save(path=archive_path)
        return archive_path

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

    def would_violate_terminal_task_invariant(
        self, *, task_id: str, closing_status: str | None
    ) -> TerminalTaskViolation | None:
        """Return a violation if closing ``task_id`` would break the invariant.

        Closing (``completed``/``deleted``) the terminal Verify-AC task, or
        the last remaining open task, empties a work-on plan's open-task set
        (GH-149). Returns a :class:`TerminalTaskViolation` naming the
        offending task so the caller builds its own message, or ``None`` when
        the close is safe — the status is not a closing status, the task is
        absent or already closed, or other open tasks remain and this is not
        the terminal task.
        """
        if closing_status not in _CLOSING_STATUSES:
            return None
        target = next((t for t in self.tasks if t.id == task_id), None)
        if target is None or target.status not in _OPEN_STATUSES:
            return None
        remaining_open = [t for t in self.tasks if t.id != task_id and t.status in _OPEN_STATUSES]
        is_terminal = bool(_TERMINAL_SUBJECT.search(target.subject or ""))
        if remaining_open and not is_terminal:
            return None
        return TerminalTaskViolation(subject=target.subject or "", is_terminal=is_terminal)

    def _find_index(self, *, task_id: str) -> int | None:
        for idx, task in enumerate(self.tasks):
            if task.id == task_id:
                return idx
        return None

    def handle_task_create(
        self,
        *,
        tool_input: dict[str, Any],
        tool_result: str,
    ) -> bool:
        task_id = _extract_task_id(tool_result)
        if not task_id:
            return False

        if any(t.id == task_id for t in self.tasks):
            return False

        metadata_raw = tool_input.get("metadata") or {}
        task = Task(
            id=task_id,
            subject=tool_input.get("subject", ""),
            status=TaskStatus.PENDING,
            created_at=_now_iso(),
            description=tool_input.get("description", "") or "",
            metadata=dict(metadata_raw) if isinstance(metadata_raw, dict) else {},
        )
        self.tasks.append(task)
        return True

    def handle_task_update(self, *, tool_input: dict[str, Any]) -> None:
        task_id = tool_input.get("taskId")
        if not task_id:
            return

        raw_status = tool_input.get("status")
        target_status = _coerce_status(raw_status)

        idx = self._find_index(task_id=task_id)
        if idx is None:
            return

        task = self.tasks[idx]
        if target_status is not None:
            if not _is_valid_transition(current=task.status, target=target_status):
                # Reject invalid transitions silently; the hook must keep
                # processing other updates rather than crashing on a stale
                # status flip caused by clock skew or replay.
                return
            # DELETED is declared with `removes=True` in TASK_TRANSITIONS —
            # the operation drops the task entry instead of restamping it.
            if TASK_TRANSITIONS[target_status].removes:
                del self.tasks[idx]
                return
            task = task.with_status(status=target_status, timestamp=_now_iso())

        if "subject" in tool_input:
            task = task.with_subject(subject=tool_input["subject"])
        if "description" in tool_input:
            task = task.with_description(description=tool_input["description"])
        if "metadata" in tool_input:
            updates = tool_input["metadata"]
            if isinstance(updates, dict):
                task = task.with_metadata_merged(updates=updates)

        self.tasks[idx] = task

    def check_all_completed(self) -> None:
        if self.tasks and all(t.status is TaskStatus.COMPLETED for t in self.tasks):
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
