"""Tests for reading a session's task list (GH-1722)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from dev10x.comm.overwatch import session_tasks
from dev10x.comm.overwatch.session_tasks import SessionTask, read_session_tasks, task_store

SESSION = "47a1ef74-ca1e-4876-bdb1-83dd7a452919"


def _task(store: Path, name: str, record: Any) -> None:
    store.mkdir(parents=True, exist_ok=True)
    (store / f"{name}.json").write_text(
        json.dumps(record) if not isinstance(record, str) else record
    )


@pytest.fixture
def store(tmp_path: Path) -> Path:
    return task_store(session_id=SESSION, tasks_root=tmp_path)


def test_store_is_keyed_by_the_short_session_id(tmp_path: Path) -> None:
    assert task_store(session_id=SESSION, tasks_root=tmp_path) == tmp_path / "session-47a1ef74"


def test_open_work_first_then_by_number(tmp_path: Path, store: Path) -> None:
    _task(store, "10", {"id": "10", "subject": "Ship", "status": "pending"})
    _task(store, "2", {"id": "2", "subject": "Gather", "status": "completed"})
    _task(
        store,
        "3",
        {"id": "3", "subject": "Build", "status": "in_progress", "activeForm": "Building"},
    )
    _task(store, "9", {"id": "9", "subject": "Plan", "status": "pending"})
    _task(store, "x", {"id": "x", "subject": "Odd id", "status": "pending"})

    assert read_session_tasks(session_id=SESSION, tasks_root=tmp_path) == [
        SessionTask(id="3", subject="Build", status="in_progress", active_form="Building"),
        SessionTask(id="x", subject="Odd id", status="pending"),
        SessionTask(id="9", subject="Plan", status="pending"),
        SessionTask(id="10", subject="Ship", status="pending"),
        SessionTask(id="2", subject="Gather", status="completed"),
    ]


def test_skips_broken_and_empty_records(tmp_path: Path, store: Path) -> None:
    _task(store, "1", "not json")
    _task(store, "2", ["a list"])
    _task(store, "3", {"id": "3", "status": "pending"})
    _task(store, "4", {"subject": "No id or status"})

    assert read_session_tasks(session_id=SESSION, tasks_root=tmp_path) == [
        SessionTask(id="4", subject="No id or status", status="pending")
    ]


def test_no_store_means_no_tasks(tmp_path: Path) -> None:
    assert read_session_tasks(session_id=SESSION, tasks_root=tmp_path) == []


def test_defaults_to_the_claude_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_tasks.ClaudeDir, "home", staticmethod(lambda: tmp_path))
    _task(
        tmp_path / "tasks" / "session-47a1ef74",
        "1",
        {"id": "1", "subject": "Only", "status": "pending"},
    )

    assert [task.subject for task in read_session_tasks(session_id=SESSION)] == ["Only"]
