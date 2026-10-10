"""Pin the plan.yaml mirror format the core reader accepts (GH-1530)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.core.plan_mirror import (
    PlanMirror,
    plan_mirror_path,
    read_plan_mirror,
    read_plan_summary,
)
from dev10x.domain.documents.plan import Plan, get_plan_path
from dev10x.domain.documents.task import Task, TaskStatus

PLAN_YAML = """\
plan:
  created_at: '2026-10-10T20:00:00+00:00'
  branch: janusz/GH-1530/plan-mirror
  status: in_progress
  last_synced: '2026-10-10T21:00:00+00:00'
  context:
    work_on: true
    tickets:
    - GH-1530
tasks:
- id: '1'
  subject: Implement the reader
  status: completed
  created_at: '2026-10-10T20:01:00+00:00'
  completed_at: '2026-10-10T20:30:00+00:00'
- id: '2'
  subject: Verify AC and close session
  status: pending
  description: PR link and CI status
  metadata:
    awaiting: supervisor
- id: '3'
  subject: Groom history
  status: in_progress
  started_at: '2026-10-10T20:40:00+00:00'
"""


@pytest.fixture
def toplevel(tmp_path: Path) -> Path:
    path = plan_mirror_path(toplevel=str(tmp_path))
    path.parent.mkdir(parents=True)
    path.write_text(PLAN_YAML)
    return tmp_path


@pytest.fixture
def mirror(toplevel: Path) -> PlanMirror:
    return read_plan_mirror(path=plan_mirror_path(toplevel=str(toplevel)))


class TestPlanMirrorFormat:
    def test_path_matches_the_writer(self, tmp_path: Path) -> None:
        assert plan_mirror_path(toplevel=str(tmp_path)) == get_plan_path(toplevel=str(tmp_path))

    def test_branch(self, mirror: PlanMirror) -> None:
        assert mirror.branch == "janusz/GH-1530/plan-mirror"

    def test_context(self, mirror: PlanMirror) -> None:
        assert mirror.context == {"work_on": True, "tickets": ["GH-1530"]}

    def test_tasks_are_typed(self, mirror: PlanMirror) -> None:
        assert mirror.tasks[1] == Task(
            id="2",
            subject="Verify AC and close session",
            status=TaskStatus.PENDING,
            description="PR link and CI status",
            metadata={"awaiting": "supervisor"},
        )

    def test_open_tasks(self, mirror: PlanMirror) -> None:
        assert [task.id for task in mirror.open_tasks] == ["2", "3"]

    def test_summary_matches_the_writer_round_trip(
        self,
        mirror: PlanMirror,
        toplevel: Path,
    ) -> None:
        expected = Plan.load(path=get_plan_path(toplevel=str(toplevel))).to_dict()

        assert mirror.to_summary() == expected

    def test_read_plan_summary_by_toplevel(self, toplevel: Path, mirror: PlanMirror) -> None:
        assert read_plan_summary(toplevel=str(toplevel)) == mirror.to_summary()

    def test_to_plan_keeps_the_guard_query(self, mirror: PlanMirror) -> None:
        violation = mirror.to_plan().would_violate_terminal_task_invariant(
            task_id="2",
            closing_status="completed",
        )

        assert violation is not None
        assert violation.is_terminal


class TestDegradedInput:
    def test_missing_file_reads_empty(self, tmp_path: Path) -> None:
        mirror = read_plan_mirror(path=tmp_path / "absent.yaml")

        assert (mirror.metadata, mirror.tasks) == ({}, ())

    @pytest.mark.parametrize(
        ("content", "branch", "context"),
        [
            ("plan:\n  branch: 7\n  context: nope\n", None, {}),
            ("- just\n- a list\n", None, {}),
        ],
    )
    def test_malformed_fields_degrade(
        self,
        tmp_path: Path,
        content: str,
        branch: str | None,
        context: dict,
    ) -> None:
        path = tmp_path / "plan.yaml"
        path.write_text(content)

        mirror = read_plan_mirror(path=path)

        assert (mirror.branch, mirror.context) == (branch, context)
