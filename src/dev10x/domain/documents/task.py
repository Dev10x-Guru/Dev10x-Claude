"""Task value object for typed plan task entries.

Replaces the `dict[str, Any]` task representation that propagated
through `Plan`, `PlanSummary`, `DecisionGuidanceRule`, and
`task_plan_sync` with ~15 string-key call sites (audit finding
B1/B10 — 2026-05-18). YAML round-trip is preserved via
`Task.from_dict` / `Task.to_dict`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any


class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    DELETED = "deleted"


@dataclass(frozen=True)
class Task:
    id: str
    subject: str = ""
    status: TaskStatus = TaskStatus.PENDING
    created_at: str = ""
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    started_at: str = ""
    completed_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Task:
        raw_status = data.get("status")
        try:
            status = TaskStatus(raw_status) if raw_status else TaskStatus.PENDING
        except ValueError:
            status = TaskStatus.PENDING
        metadata = data.get("metadata") or {}
        return cls(
            id=str(data.get("id", "")),
            subject=data.get("subject", ""),
            status=status,
            created_at=data.get("created_at", ""),
            description=data.get("description", ""),
            metadata=dict(metadata) if isinstance(metadata, dict) else {},
            started_at=data.get("started_at", ""),
            completed_at=data.get("completed_at", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "subject": self.subject,
            "status": self.status.value,
        }
        if self.created_at:
            result["created_at"] = self.created_at
        if self.description:
            result["description"] = self.description
        if self.metadata:
            result["metadata"] = self.metadata
        if self.started_at:
            result["started_at"] = self.started_at
        if self.completed_at:
            result["completed_at"] = self.completed_at
        return result

    def with_status(self, *, status: TaskStatus, timestamp: str) -> Task:
        if status is TaskStatus.IN_PROGRESS:
            return replace(self, status=status, started_at=timestamp)
        if status is TaskStatus.COMPLETED:
            return replace(self, status=status, completed_at=timestamp)
        return replace(self, status=status)

    def with_subject(self, *, subject: str) -> Task:
        return replace(self, subject=subject)

    def with_description(self, *, description: str) -> Task:
        return replace(self, description=description)

    def with_metadata_merged(self, *, updates: dict[str, Any]) -> Task:
        merged = dict(self.metadata)
        for k, v in updates.items():
            if v is None:
                merged.pop(k, None)
            else:
                merged[k] = v
        return replace(self, metadata=merged)

    @property
    def is_active(self) -> bool:
        return self.status in (TaskStatus.PENDING, TaskStatus.IN_PROGRESS)
