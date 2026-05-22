from __future__ import annotations

import pytest

from dev10x.domain.documents.task import Task, TaskStatus


class TestTaskFromDict:
    def test_parses_minimal_dict(self) -> None:
        task = Task.from_dict({"id": "1"})

        assert task.id == "1"
        assert task.status is TaskStatus.PENDING
        assert task.metadata == {}

    def test_parses_full_dict(self) -> None:
        task = Task.from_dict(
            {
                "id": "5",
                "subject": "Do thing",
                "status": "in_progress",
                "created_at": "2026-01-01",
                "description": "Details",
                "metadata": {"type": "epic"},
                "started_at": "2026-01-02",
                "completed_at": "",
            }
        )

        assert task.id == "5"
        assert task.subject == "Do thing"
        assert task.status is TaskStatus.IN_PROGRESS
        assert task.description == "Details"
        assert task.metadata == {"type": "epic"}
        assert task.started_at == "2026-01-02"

    def test_falls_back_to_pending_for_unknown_status(self) -> None:
        task = Task.from_dict({"id": "1", "status": "bogus"})

        assert task.status is TaskStatus.PENDING

    def test_coerces_id_to_str(self) -> None:
        task = Task.from_dict({"id": 42})

        assert task.id == "42"

    def test_treats_non_dict_metadata_as_empty(self) -> None:
        task = Task.from_dict({"id": "1", "metadata": "not-a-dict"})

        assert task.metadata == {}


class TestTaskToDict:
    def test_omits_empty_optional_fields(self) -> None:
        task = Task(id="1", subject="X")

        result = task.to_dict()

        assert result == {"id": "1", "subject": "X", "status": "pending"}

    def test_includes_populated_fields(self) -> None:
        task = Task(
            id="1",
            subject="X",
            status=TaskStatus.COMPLETED,
            created_at="ts",
            description="d",
            metadata={"k": "v"},
            completed_at="t2",
        )

        result = task.to_dict()

        assert result["status"] == "completed"
        assert result["description"] == "d"
        assert result["metadata"] == {"k": "v"}
        assert result["completed_at"] == "t2"


class TestTaskTransitions:
    def test_with_status_in_progress_sets_started_at(self) -> None:
        task = Task(id="1")

        updated = task.with_status(status=TaskStatus.IN_PROGRESS, timestamp="now")

        assert updated.status is TaskStatus.IN_PROGRESS
        assert updated.started_at == "now"

    def test_with_status_completed_sets_completed_at(self) -> None:
        task = Task(id="1")

        updated = task.with_status(status=TaskStatus.COMPLETED, timestamp="now")

        assert updated.status is TaskStatus.COMPLETED
        assert updated.completed_at == "now"

    def test_with_status_pending_leaves_timestamps_empty(self) -> None:
        task = Task(id="1")

        updated = task.with_status(status=TaskStatus.PENDING, timestamp="now")

        assert updated.started_at == ""
        assert updated.completed_at == ""


class TestTaskMerge:
    def test_with_metadata_merged_adds_keys(self) -> None:
        task = Task(id="1", metadata={"type": "epic"})

        merged = task.with_metadata_merged(updates={"skills": ["test"]})

        assert merged.metadata == {"type": "epic", "skills": ["test"]}

    def test_with_metadata_merged_removes_none_keys(self) -> None:
        task = Task(id="1", metadata={"type": "epic", "old": "v"})

        merged = task.with_metadata_merged(updates={"old": None})

        assert merged.metadata == {"type": "epic"}


class TestTaskIsActive:
    @pytest.mark.parametrize(
        "status,expected",
        [
            (TaskStatus.PENDING, True),
            (TaskStatus.IN_PROGRESS, True),
            (TaskStatus.COMPLETED, False),
            (TaskStatus.DELETED, False),
        ],
    )
    def test_is_active(self, status: TaskStatus, expected: bool) -> None:
        assert Task(id="1", status=status).is_active is expected
