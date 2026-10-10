"""Read-only view of the ``plan.yaml`` task mirror (ADR-0034, GH-1530).

The plan-sync hooks write ``<toplevel>/.claude/session/plan.yaml``; the
Stop verdict and the task guard only read it. Core owns this reader so
that when the writer moves to the task-management plugin (NS-15), the
readers keep a stable contract. The schema is documented in
``references/plan-mirror-schema.md``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dev10x.domain.documents.plan import Plan
from dev10x.domain.documents.task import Task, TaskStatus

PLAN_MIRROR_PARTS = (".claude", "session", "plan.yaml")
OPEN_STATUSES = (TaskStatus.PENDING, TaskStatus.IN_PROGRESS)


@dataclass(frozen=True)
class PlanMirror:
    metadata: Mapping[str, Any]
    tasks: tuple[Task, ...]

    @property
    def branch(self) -> str | None:
        branch = self.metadata.get("branch")
        return branch if isinstance(branch, str) else None

    @property
    def context(self) -> Mapping[str, Any]:
        context = self.metadata.get("context")
        return context if isinstance(context, Mapping) else {}

    @property
    def open_tasks(self) -> tuple[Task, ...]:
        return tuple(task for task in self.tasks if task.status in OPEN_STATUSES)

    def to_summary(self) -> dict[str, Any]:
        return self.to_plan().to_dict()

    def to_plan(self) -> Plan:
        return Plan(metadata=dict(self.metadata), tasks=list(self.tasks))


def plan_mirror_path(*, toplevel: str) -> Path:
    return Path(toplevel).joinpath(*PLAN_MIRROR_PARTS)


def read_plan_mirror(*, path: Path) -> PlanMirror:
    plan = Plan.load(path=path)
    return PlanMirror(metadata=plan.metadata, tasks=tuple(plan.tasks))


def read_plan_summary(*, toplevel: str) -> dict[str, Any]:
    return read_plan_mirror(path=plan_mirror_path(toplevel=toplevel)).to_summary()


__all__ = [
    "OPEN_STATUSES",
    "PLAN_MIRROR_PARTS",
    "PlanMirror",
    "plan_mirror_path",
    "read_plan_mirror",
    "read_plan_summary",
]
