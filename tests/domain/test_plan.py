from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from dev10x.domain.documents.plan import (
    TASK_TRANSITIONS,
    Plan,
    TaskStatus,
    _extract_task_id,
    _set_nested,
    get_plan_path,
)
from dev10x.domain.documents.task import Task


class TestExtractTaskId:
    def test_extracts_id_from_standard_output(self) -> None:
        assert _extract_task_id("Task #42 created successfully") == "42"

    def test_returns_none_for_no_match(self) -> None:
        assert _extract_task_id("No task here") is None

    def test_extracts_first_match(self) -> None:
        assert _extract_task_id("Task #1 and Task #2") == "1"


class TestSetNested:
    def test_sets_top_level_key(self) -> None:
        d: dict = {}
        _set_nested(d=d, dotpath="key", value="val")

        assert d == {"key": "val"}

    def test_sets_nested_key(self) -> None:
        d: dict = {}
        _set_nested(d=d, dotpath="a.b.c", value="val")

        assert d == {"a": {"b": {"c": "val"}}}

    def test_parses_json_value(self) -> None:
        d: dict = {}
        _set_nested(d=d, dotpath="items", value='["a","b"]')

        assert d == {"items": ["a", "b"]}

    def test_keeps_string_for_invalid_json(self) -> None:
        d: dict = {}
        _set_nested(d=d, dotpath="key", value="plain text")

        assert d == {"key": "plain text"}


class TestPlanLoad:
    def test_loads_from_yaml(self, tmp_path: Path) -> None:
        plan_path = tmp_path / "plan.yaml"
        plan_path.write_text(
            yaml.dump(
                {
                    "plan": {"status": "in_progress", "branch": "feature"},
                    "tasks": [{"id": "1", "subject": "Task one", "status": "pending"}],
                }
            )
        )

        plan = Plan.load(path=plan_path)

        assert plan.metadata["status"] == "in_progress"
        assert len(plan.tasks) == 1
        assert plan.tasks[0].id == "1"
        assert plan.tasks[0].status is TaskStatus.PENDING

    def test_returns_empty_for_missing_file(self, tmp_path: Path) -> None:
        plan = Plan.load(path=tmp_path / "nonexistent.yaml")

        assert plan.metadata == {}
        assert plan.tasks == []

    def test_returns_empty_for_corrupt_yaml(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text(": [invalid yaml")

        plan = Plan.load(path=path)

        assert plan.metadata == {}
        assert plan.tasks == []


class TestPlanSave:
    def test_round_trips_through_save_and_load(self, tmp_path: Path) -> None:
        path = tmp_path / "session" / "plan.yaml"
        plan = Plan(
            metadata={"status": "in_progress"},
            tasks=[Task(id="1", subject="Test", status=TaskStatus.PENDING)],
        )

        plan.save(path=path)
        loaded = Plan.load(path=path)

        assert loaded.metadata["status"] == "in_progress"
        assert len(loaded.tasks) == 1
        assert loaded.tasks[0].subject == "Test"

    def test_round_trips_dict_tasks(self, tmp_path: Path) -> None:
        # Legacy callers may still construct Plan with raw dict tasks —
        # post_init normalizes them to Task instances.
        path = tmp_path / "session" / "plan.yaml"
        plan = Plan(
            metadata={"status": "in_progress"},
            tasks=[{"id": "1", "subject": "Test", "status": "pending"}],
        )

        plan.save(path=path)
        loaded = Plan.load(path=path)

        assert loaded.tasks[0].id == "1"

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        path = tmp_path / "deep" / "nested" / "plan.yaml"

        Plan(metadata={"status": "new"}).save(path=path)

        assert path.exists()

    def test_save_leaves_no_stale_tmp(self, tmp_path: Path) -> None:
        # GH-571: Plan.save now routes through atomic_write_text
        # (mkstemp + fsync + rename), so no .tmp sidecar survives.
        path = tmp_path / "plan.yaml"

        Plan(metadata={"status": "new"}).save(path=path)

        leftovers = [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"]
        assert leftovers == []


class TestPlanIsNew:
    def test_true_when_no_metadata(self) -> None:
        assert Plan().is_new is True

    def test_false_when_metadata_exists(self) -> None:
        assert Plan(metadata={"status": "in_progress"}).is_new is False


class TestPlanHandleTaskCreate:
    @pytest.fixture()
    def plan(self) -> Plan:
        return Plan(metadata={"status": "in_progress"})

    def test_appends_task(self, plan: Plan) -> None:
        result = plan.handle_task_create(
            tool_input={"subject": "Do thing", "description": "Details"},
            tool_result="Task #1 created successfully",
        )

        assert result is True
        assert len(plan.tasks) == 1
        assert plan.tasks[0].id == "1"
        assert plan.tasks[0].subject == "Do thing"
        assert plan.tasks[0].description == "Details"

    def test_returns_false_for_unparseable_result(self, plan: Plan) -> None:
        result = plan.handle_task_create(
            tool_input={"subject": "Do thing"},
            tool_result="Something went wrong",
        )

        assert result is False
        assert len(plan.tasks) == 0

    def test_skips_duplicate_ids(self, plan: Plan) -> None:
        plan.tasks = [Task(id="1", subject="Existing", status=TaskStatus.PENDING)]

        result = plan.handle_task_create(
            tool_input={"subject": "Duplicate"},
            tool_result="Task #1 created successfully",
        )

        assert result is False
        assert len(plan.tasks) == 1

    def test_includes_metadata_when_provided(self, plan: Plan) -> None:
        plan.handle_task_create(
            tool_input={"subject": "T", "metadata": {"type": "epic"}},
            tool_result="Task #5 created successfully",
        )

        assert plan.tasks[0].metadata == {"type": "epic"}


class TestPlanHandleTaskUpdate:
    @pytest.fixture()
    def plan(self) -> Plan:
        return Plan(
            metadata={"status": "in_progress"},
            tasks=[
                Task(id="1", subject="First", status=TaskStatus.PENDING),
                Task(id="2", subject="Second", status=TaskStatus.PENDING),
            ],
        )

    def test_updates_status(self, plan: Plan) -> None:
        plan.handle_task_update(tool_input={"taskId": "1", "status": "in_progress"})

        assert plan.tasks[0].status is TaskStatus.IN_PROGRESS
        assert plan.tasks[0].started_at != ""

    def test_marks_completed_with_timestamp(self, plan: Plan) -> None:
        plan.handle_task_update(tool_input={"taskId": "1", "status": "completed"})

        assert plan.tasks[0].status is TaskStatus.COMPLETED
        assert plan.tasks[0].completed_at != ""

    def test_deletes_task(self, plan: Plan) -> None:
        plan.handle_task_update(tool_input={"taskId": "1", "status": "deleted"})

        assert len(plan.tasks) == 1
        assert plan.tasks[0].id == "2"

    def test_updates_subject(self, plan: Plan) -> None:
        plan.handle_task_update(tool_input={"taskId": "1", "subject": "Updated"})

        assert plan.tasks[0].subject == "Updated"

    def test_merges_metadata(self, plan: Plan) -> None:
        plan.tasks[0] = plan.tasks[0].with_metadata_merged(updates={"type": "epic"})

        plan.handle_task_update(tool_input={"taskId": "1", "metadata": {"skills": ["test"]}})

        assert plan.tasks[0].metadata == {"type": "epic", "skills": ["test"]}

    def test_removes_metadata_key_with_none(self, plan: Plan) -> None:
        plan.tasks[0] = plan.tasks[0].with_metadata_merged(
            updates={"type": "epic", "old": "value"}
        )

        plan.handle_task_update(tool_input={"taskId": "1", "metadata": {"old": None}})

        assert plan.tasks[0].metadata == {"type": "epic"}

    def test_ignores_missing_task_id(self, plan: Plan) -> None:
        plan.handle_task_update(tool_input={})

        assert len(plan.tasks) == 2


class TestPlanCheckAllCompleted:
    def test_marks_plan_completed_when_all_tasks_done(self) -> None:
        plan = Plan(
            metadata={"status": "in_progress"},
            tasks=[
                Task(id="1", status=TaskStatus.COMPLETED),
                Task(id="2", status=TaskStatus.COMPLETED),
            ],
        )

        plan.check_all_completed()

        assert plan.metadata["status"] == "completed"
        assert "completed_at" in plan.metadata

    def test_does_not_mark_when_tasks_pending(self) -> None:
        plan = Plan(
            metadata={"status": "in_progress"},
            tasks=[
                Task(id="1", status=TaskStatus.COMPLETED),
                Task(id="2", status=TaskStatus.PENDING),
            ],
        )

        plan.check_all_completed()

        assert plan.metadata["status"] == "in_progress"

    def test_does_nothing_for_empty_tasks(self) -> None:
        plan = Plan(metadata={"status": "in_progress"})

        plan.check_all_completed()

        assert plan.metadata["status"] == "in_progress"


class TestPlanSetContext:
    def test_sets_simple_key(self) -> None:
        plan = Plan(metadata={"context": {}})

        plan.set_context(key="work_type", value="feature")

        assert plan.metadata["context"]["work_type"] == "feature"

    def test_sets_nested_key(self) -> None:
        plan = Plan(metadata={})

        plan.set_context(key="routing.commit", value="Skill(Dev10x:git-commit)")

        assert plan.metadata["context"]["routing"]["commit"] == "Skill(Dev10x:git-commit)"

    def test_parses_json_list(self) -> None:
        plan = Plan(metadata={})

        plan.set_context(key="tickets", value='["GH-1","GH-2"]')

        assert plan.metadata["context"]["tickets"] == ["GH-1", "GH-2"]


class TestPlanEnsureMetadata:
    @patch("dev10x.domain.documents.plan._get_branch", return_value="feature/test")
    def test_initializes_empty_metadata(self, _mock_branch: object) -> None:
        plan = Plan()

        plan.ensure_metadata()

        assert plan.metadata["branch"] == "feature/test"
        assert plan.metadata["status"] == "in_progress"
        assert "created_at" in plan.metadata
        assert "last_synced" in plan.metadata

    @patch("dev10x.domain.documents.plan._get_branch", return_value="feature/test")
    def test_updates_last_synced_on_existing(self, _mock_branch: object) -> None:
        plan = Plan(metadata={"status": "in_progress", "branch": "old"})

        plan.ensure_metadata()

        assert plan.metadata["branch"] == "old"
        assert "last_synced" in plan.metadata


class TestPlanArchive:
    def test_stamps_archived_at_and_saves(self, tmp_path: Path) -> None:
        plan = Plan(metadata={"status": "completed"})
        archive_path = tmp_path / "archive" / "plan.yaml"

        plan.archive(path=archive_path)

        assert archive_path.exists()
        assert "archived_at" in plan.metadata
        loaded = Plan.load(path=archive_path)
        assert "archived_at" in loaded.metadata


class TestPlanContextKeys:
    def test_returns_empty_when_no_context(self) -> None:
        assert Plan(metadata={"status": "x"}).context_keys() == []

    def test_returns_context_keys(self) -> None:
        plan = Plan(metadata={"context": {"work_type": "feature", "tickets": []}})

        assert sorted(plan.context_keys()) == ["tickets", "work_type"]

    def test_returns_empty_when_context_not_dict(self) -> None:
        plan = Plan(metadata={"context": "broken"})

        assert plan.context_keys() == []


class TestTaskTransitions:
    def test_pending_has_no_timestamp(self) -> None:
        assert TASK_TRANSITIONS[TaskStatus.PENDING].timestamp_field is None

    def test_in_progress_writes_started_at(self) -> None:
        assert TASK_TRANSITIONS[TaskStatus.IN_PROGRESS].timestamp_field == "started_at"

    def test_completed_writes_completed_at(self) -> None:
        assert TASK_TRANSITIONS[TaskStatus.COMPLETED].timestamp_field == "completed_at"

    def test_completed_to_in_progress_rejected(self) -> None:
        plan = Plan(
            metadata={"status": "in_progress"},
            tasks=[Task(id="1", status=TaskStatus.COMPLETED, completed_at="old")],
        )

        plan.handle_task_update(tool_input={"taskId": "1", "status": "in_progress"})

        assert plan.tasks[0].status is TaskStatus.COMPLETED
        assert plan.tasks[0].started_at == ""

    def test_unknown_status_silently_skipped(self) -> None:
        plan = Plan(
            metadata={"status": "in_progress"},
            tasks=[Task(id="1", status=TaskStatus.PENDING)],
        )

        plan.handle_task_update(tool_input={"taskId": "1", "status": "bogus"})

        assert plan.tasks[0].status is TaskStatus.PENDING


class TestGetPlanPath:
    def test_joins_toplevel_with_session_plan(self, tmp_path: Path) -> None:
        path = get_plan_path(toplevel=str(tmp_path))

        assert path == tmp_path / ".claude" / "session" / "plan.yaml"
