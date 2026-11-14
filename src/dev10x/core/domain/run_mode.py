"""Resolved run mode: is anyone watching this skill run? (GH-1921).

``references/review-readiness.md`` calls a run unattended when the
caller passes ``--unattended`` *or* when an orchestrator invokes the
skill while executing a plan step. Nothing let a callee see the second
state, so a real plan-step call could fall back to attended. This module
derives that state from structured inputs only — the resolved gate
overlays and the plan-sync task mirror — and reports ``undetermined``
with its basis when those inputs cannot settle it, rather than picking a
default the caller cannot see.

The ``--unattended`` flag is not an input here: it is the caller's own
argument, and it wins over this fact wherever both are read.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from dev10x.domain.documents.task import Task, TaskStatus

AFK_OVERLAY = "afk"

#: Metadata keys ``dev10x:work-on`` writes on every plan-step task it
#: creates from a play (``type``, plus ``skills`` / ``agent`` when the
#: step names them). A task the supervisor or a callee created by hand
#: carries none of them.
PLAN_STEP_METADATA_KEYS = ("type", "skills", "agent")


class RunMode(StrEnum):
    UNATTENDED = "unattended"
    ATTENDED = "attended"
    UNDETERMINED = "undetermined"


class RunModeBasis(StrEnum):
    AFK_OVERLAY = "afk-overlay"
    PLAN_STEP_IN_PROGRESS = "plan-step-in-progress"
    NO_PLAN_STEP_IN_PROGRESS = "no-plan-step-in-progress"
    NO_PLAN_MIRROR = "no-plan-mirror"
    PLAN_MIRROR_HAS_NO_TASKS = "plan-mirror-has-no-tasks"
    PLAN_MIRROR_OTHER_BRANCH = "plan-mirror-other-branch"


@dataclass(frozen=True)
class PlanState:
    """The slice of the plan-sync mirror the run-mode rule reads."""

    present: bool
    branch: str | None
    tasks: tuple[Task, ...]


@dataclass(frozen=True)
class RunModeResolution:
    mode: RunMode
    basis: RunModeBasis
    plan_step: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"mode": self.mode.value, "basis": self.basis.value}
        if self.plan_step is not None:
            payload["plan_step"] = self.plan_step
        return payload


def is_plan_step(*, task: Task) -> bool:
    return any(key in task.metadata for key in PLAN_STEP_METADATA_KEYS)


def _in_progress_plan_step(*, tasks: Sequence[Task]) -> Task | None:
    for task in tasks:
        if task.status == TaskStatus.IN_PROGRESS and is_plan_step(task=task):
            return task
    return None


def resolve_run_mode(
    *,
    overlays: Sequence[str],
    plan: PlanState,
    current_branch: str | None,
) -> RunModeResolution:
    if AFK_OVERLAY in overlays:
        return RunModeResolution(mode=RunMode.UNATTENDED, basis=RunModeBasis.AFK_OVERLAY)
    if not plan.present:
        return RunModeResolution(mode=RunMode.UNDETERMINED, basis=RunModeBasis.NO_PLAN_MIRROR)
    if plan.branch is not None and plan.branch != current_branch:
        return RunModeResolution(
            mode=RunMode.UNDETERMINED, basis=RunModeBasis.PLAN_MIRROR_OTHER_BRANCH
        )
    # GH-1055: a session without the task tools mirrors no tasks, so an
    # empty list is not evidence that nobody is orchestrating.
    if not plan.tasks:
        return RunModeResolution(
            mode=RunMode.UNDETERMINED, basis=RunModeBasis.PLAN_MIRROR_HAS_NO_TASKS
        )
    step = _in_progress_plan_step(tasks=plan.tasks)
    if step is None:
        return RunModeResolution(
            mode=RunMode.ATTENDED, basis=RunModeBasis.NO_PLAN_STEP_IN_PROGRESS
        )
    return RunModeResolution(
        mode=RunMode.UNATTENDED,
        basis=RunModeBasis.PLAN_STEP_IN_PROGRESS,
        plan_step=step.subject,
    )


__all__ = [
    "AFK_OVERLAY",
    "PLAN_STEP_METADATA_KEYS",
    "PlanState",
    "RunMode",
    "RunModeBasis",
    "RunModeResolution",
    "is_plan_step",
    "resolve_run_mode",
]
