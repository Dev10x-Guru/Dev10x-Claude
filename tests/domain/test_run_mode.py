"""GH-1921: the resolved run mode is derived from structured state only."""

from __future__ import annotations

import pytest
from dev10x.domain.documents.task import Task, TaskStatus
from dev10x.domain.run_mode import (
    PlanState,
    RunMode,
    RunModeBasis,
    RunModeResolution,
    is_plan_step,
    resolve_run_mode,
)

BRANCH = "janusz/GH-1921/resolved-run-mode"


def _task(*, status: TaskStatus, metadata: dict | None = None, subject: str = "Step") -> Task:
    return Task(id="1", subject=subject, status=status, metadata=metadata or {})


def _plan(*tasks: Task, branch: str | None = BRANCH, present: bool = True) -> PlanState:
    return PlanState(present=present, branch=branch, tasks=tasks)


class TestIsPlanStep:
    @pytest.mark.parametrize(
        ("metadata", "expected"),
        [
            ({"type": "detailed"}, True),
            ({"skills": ["dev10x:request-review"]}, True),
            ({"agent": "reviewer-generic"}, True),
            ({"awaiting": "subagent"}, False),
            ({}, False),
        ],
    )
    def test_reads_the_work_on_step_keys(self, metadata: dict, expected: bool) -> None:
        assert is_plan_step(task=_task(status=TaskStatus.PENDING, metadata=metadata)) is expected


class TestResolveRunMode:
    @pytest.mark.parametrize(
        ("overlays", "plan", "current_branch", "mode", "basis"),
        [
            (
                ["solo-maintainer", "afk"],
                _plan(present=False),
                BRANCH,
                RunMode.UNATTENDED,
                RunModeBasis.AFK_OVERLAY,
            ),
            ([], _plan(present=False), BRANCH, RunMode.UNDETERMINED, RunModeBasis.NO_PLAN_MIRROR),
            (
                [],
                _plan(_task(status=TaskStatus.IN_PROGRESS, metadata={"type": "x"}), branch="old"),
                BRANCH,
                RunMode.UNDETERMINED,
                RunModeBasis.PLAN_MIRROR_OTHER_BRANCH,
            ),
            ([], _plan(), BRANCH, RunMode.UNDETERMINED, RunModeBasis.PLAN_MIRROR_HAS_NO_TASKS),
            (
                [],
                _plan(
                    _task(status=TaskStatus.PENDING, metadata={"type": "detailed"}),
                    _task(status=TaskStatus.IN_PROGRESS),
                ),
                BRANCH,
                RunMode.ATTENDED,
                RunModeBasis.NO_PLAN_STEP_IN_PROGRESS,
            ),
            (
                [],
                _plan(
                    _task(status=TaskStatus.COMPLETED, metadata={"type": "detailed"}),
                    _task(status=TaskStatus.IN_PROGRESS, metadata={"skills": ["x"]}),
                ),
                BRANCH,
                RunMode.UNATTENDED,
                RunModeBasis.PLAN_STEP_IN_PROGRESS,
            ),
            (
                [],
                _plan(
                    _task(status=TaskStatus.IN_PROGRESS, metadata={"type": "detailed"}),
                    branch=None,
                ),
                BRANCH,
                RunMode.UNATTENDED,
                RunModeBasis.PLAN_STEP_IN_PROGRESS,
            ),
        ],
        ids=[
            "afk-overlay",
            "no-plan-mirror",
            "other-branch",
            "no-tasks",
            "no-step-in-progress",
            "step-in-progress",
            "step-in-progress-without-branch",
        ],
    )
    def test_mode_and_basis(
        self,
        overlays: list[str],
        plan: PlanState,
        current_branch: str,
        mode: RunMode,
        basis: RunModeBasis,
    ) -> None:
        resolution = resolve_run_mode(overlays=overlays, plan=plan, current_branch=current_branch)

        assert (resolution.mode, resolution.basis) == (mode, basis)

    def test_names_the_plan_step_in_progress(self) -> None:
        plan = _plan(
            _task(
                status=TaskStatus.IN_PROGRESS,
                metadata={"skills": ["dev10x:gh-pr-monitor"]},
                subject="Monitor CI",
            )
        )

        resolution = resolve_run_mode(overlays=[], plan=plan, current_branch=BRANCH)

        assert resolution.plan_step == "Monitor CI"


class TestToPayload:
    @pytest.mark.parametrize(
        ("resolution", "expected"),
        [
            (
                RunModeResolution(mode=RunMode.UNDETERMINED, basis=RunModeBasis.NO_PLAN_MIRROR),
                {"mode": "undetermined", "basis": "no-plan-mirror"},
            ),
            (
                RunModeResolution(
                    mode=RunMode.UNATTENDED,
                    basis=RunModeBasis.PLAN_STEP_IN_PROGRESS,
                    plan_step="Monitor CI",
                ),
                {
                    "mode": "unattended",
                    "basis": "plan-step-in-progress",
                    "plan_step": "Monitor CI",
                },
            ),
        ],
    )
    def test_wire_shape(self, resolution: RunModeResolution, expected: dict) -> None:
        assert resolution.to_payload() == expected
