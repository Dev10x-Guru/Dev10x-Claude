"""Tests for task-plan-sync.py PostToolUse hook."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from dev10x.hooks.task_plan_sync import _tool_outcome

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = _REPO_ROOT / "hooks" / "scripts" / "task-plan-sync.py"

# GH-1514: every hook run used to target the checkout running the tests,
# and the cleanup fixture unlinked that checkout's live
# `.claude/session/plan.yaml` (and TestArchive its `archive/`). A full
# suite run inside an active work-on session wiped the task mirror the
# Stop hook reads, which then reported "the task list is empty" while
# the harness still held open tasks. Each test now gets its own repo.
_SANDBOX: Path | None = None


def _sandbox() -> Path:
    assert _SANDBOX is not None, "plan_sandbox fixture did not run"
    return _SANDBOX


@pytest.fixture(autouse=True)
def plan_sandbox(sandbox_repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(sys.modules[__name__], "_SANDBOX", sandbox_repo)
    return sandbox_repo


def _plan_path() -> Path:
    return _sandbox() / ".claude" / "session" / "plan.yaml"


def _run_hook(
    *,
    payload: dict | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(HOOK)],
        input=json.dumps(payload or {}),
        capture_output=True,
        text=True,
        timeout=10,
        env={**os.environ, **(env or {})},
        cwd=_sandbox(),
    )


def _run_hook_raw(*, stdin: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(HOOK)],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=10,
        env=os.environ.copy(),
        cwd=_sandbox(),
    )


def _plan_files() -> list[Path]:
    return [_plan_path()] if _plan_path().exists() else []


def _read_plan_yaml() -> dict:
    files = _plan_files()
    assert len(files) == 1, f"Expected 1 plan file, found {len(files)}"
    result = subprocess.run(
        [str(HOOK), "--json-summary"],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=_sandbox(),
    )
    return json.loads(result.stdout)


class TestTheOutcomeSeam:
    """The hook runs as a subprocess, so this seam needs in-process cover.

    `_tool_outcome` is what lets a payload carrying only `tool_response`
    reach the handler (GH-1309).
    """

    def test_a_structured_response_is_passed_through(self) -> None:
        payload = {"tool_response": {"task": {"id": "3"}}}

        assert _tool_outcome(payload=payload) == {"task": {"id": "3"}}

    def test_a_rendered_result_still_wins(self) -> None:
        payload = {"tool_result": "Task #9 created", "tool_response": {"task": {"id": "1"}}}

        assert _tool_outcome(payload=payload) == "Task #9 created"

    def test_a_wrapped_result_is_unwrapped(self) -> None:
        """The older payload nested the rendered text under `content`."""
        payload = {"tool_result": {"content": "Task #4 created"}}

        assert _tool_outcome(payload=payload) == "Task #4 created"

    def test_an_empty_payload_yields_nothing(self) -> None:
        assert _tool_outcome(payload={}) == ""


class TestTaskCreate:
    def test_creates_plan_file(self) -> None:
        result = _run_hook(
            payload={
                "tool_name": "TaskCreate",
                "tool_input": {
                    "subject": "Test task",
                    "description": "A test task",
                },
                "tool_result": "Task #1 created successfully: Test task",
            },
        )
        assert result.returncode == 0
        assert len(_plan_files()) == 1

    def test_task_added_to_plan(self) -> None:
        _run_hook(
            payload={
                "tool_name": "TaskCreate",
                "tool_input": {
                    "subject": "Build feature",
                    "description": "Implement the feature",
                },
                "tool_result": "Task #3 created successfully: Build feature",
            },
        )
        plan = _read_plan_yaml()
        assert len(plan["tasks"]) == 1
        task = plan["tasks"][0]
        assert task["id"] == "3"
        assert task["subject"] == "Build feature"
        assert task["status"] == "pending"
        assert "created_at" in task

    def test_a_structured_tool_response_persists_the_task(self) -> None:
        """GH-1309: current Claude Code sends the created task, not prose.

        The hook read `tool_result` and regex-matched the rendered string
        a previous harness wrote. Against 2.1.263+ that field is absent,
        so every `TaskCreate` was silently dropped — Claude Code's own
        task list held the task, the hook exited 0, and `plan.yaml` had
        no `tasks` key at all.
        """
        _run_hook(
            payload={
                "tool_name": "TaskCreate",
                "tool_input": {"subject": "payload capture canary"},
                "tool_response": {"task": {"id": "1", "subject": "payload capture canary"}},
            },
        )
        plan = _read_plan_yaml()
        assert len(plan["tasks"]) == 1
        assert plan["tasks"][0]["id"] == "1"
        assert plan["tasks"][0]["subject"] == "payload capture canary"

    def test_an_integer_task_id_is_read_too(self) -> None:
        """The id is JSON, so it may arrive unquoted."""
        _run_hook(
            payload={
                "tool_name": "TaskCreate",
                "tool_input": {"subject": "Numeric id"},
                "tool_response": {"task": {"id": 7}},
            },
        )
        plan = _read_plan_yaml()
        assert plan["tasks"][0]["id"] == "7"

    def test_a_response_without_a_task_creates_nothing(self) -> None:
        """An unrecognised shape must not invent a task."""
        result = _run_hook(
            payload={
                "tool_name": "TaskCreate",
                "tool_input": {"subject": "No id anywhere"},
                "tool_response": {"ok": True},
            },
        )
        assert result.returncode == 0
        assert _plan_files() == []

    def test_plan_metadata_initialized(self) -> None:
        _run_hook(
            payload={
                "tool_name": "TaskCreate",
                "tool_input": {"subject": "First task"},
                "tool_result": "Task #1 created successfully: First task",
            },
        )
        plan = _read_plan_yaml()
        assert "plan" in plan
        assert "created_at" in plan["plan"]
        assert "branch" in plan["plan"]
        assert plan["plan"]["status"] == "in_progress"

    def test_preserves_metadata(self) -> None:
        _run_hook(
            payload={
                "tool_name": "TaskCreate",
                "tool_input": {
                    "subject": "Epic task",
                    "metadata": {"type": "epic", "skills": ["test"]},
                },
                "tool_result": "Task #2 created successfully: Epic task",
            },
        )
        plan = _read_plan_yaml()
        assert plan["tasks"][0]["metadata"]["type"] == "epic"
        assert plan["tasks"][0]["metadata"]["skills"] == ["test"]

    def test_no_duplicate_task_ids(self) -> None:
        payload = {
            "tool_name": "TaskCreate",
            "tool_input": {"subject": "Same task"},
            "tool_result": "Task #1 created successfully: Same task",
        }
        _run_hook(payload=payload)
        _run_hook(payload=payload)
        plan = _read_plan_yaml()
        assert len(plan["tasks"]) == 1

    def test_multiple_tasks(self) -> None:
        for i in range(1, 4):
            _run_hook(
                payload={
                    "tool_name": "TaskCreate",
                    "tool_input": {"subject": f"Task {i}"},
                    "tool_result": f"Task #{i} created successfully: Task {i}",
                },
            )
        plan = _read_plan_yaml()
        assert len(plan["tasks"]) == 3
        assert [t["id"] for t in plan["tasks"]] == ["1", "2", "3"]


class TestTaskUpdate:
    @pytest.fixture(autouse=True)
    def _seed_plan(self) -> None:
        for i in range(1, 3):
            _run_hook(
                payload={
                    "tool_name": "TaskCreate",
                    "tool_input": {"subject": f"Task {i}"},
                    "tool_result": f"Task #{i} created successfully: Task {i}",
                },
            )

    def test_update_status_to_in_progress(self) -> None:
        _run_hook(
            payload={
                "tool_name": "TaskUpdate",
                "tool_input": {"taskId": "1", "status": "in_progress"},
                "tool_result": "Updated task #1 status",
            },
        )
        plan = _read_plan_yaml()
        task = next(t for t in plan["tasks"] if t["id"] == "1")
        assert task["status"] == "in_progress"
        assert "started_at" in task

    def test_update_status_to_completed(self) -> None:
        _run_hook(
            payload={
                "tool_name": "TaskUpdate",
                "tool_input": {"taskId": "1", "status": "completed"},
                "tool_result": "Updated task #1 status",
            },
        )
        plan = _read_plan_yaml()
        task = next(t for t in plan["tasks"] if t["id"] == "1")
        assert task["status"] == "completed"
        assert "completed_at" in task

    def test_delete_removes_task(self) -> None:
        _run_hook(
            payload={
                "tool_name": "TaskUpdate",
                "tool_input": {"taskId": "1", "status": "deleted"},
                "tool_result": "Updated task #1 status",
            },
        )
        plan = _read_plan_yaml()
        assert len(plan["tasks"]) == 1
        assert plan["tasks"][0]["id"] == "2"

    def test_update_subject(self) -> None:
        _run_hook(
            payload={
                "tool_name": "TaskUpdate",
                "tool_input": {"taskId": "1", "subject": "Renamed task"},
                "tool_result": "Updated task #1 subject",
            },
        )
        plan = _read_plan_yaml()
        task = next(t for t in plan["tasks"] if t["id"] == "1")
        assert task["subject"] == "Renamed task"

    def test_merge_metadata(self) -> None:
        _run_hook(
            payload={
                "tool_name": "TaskCreate",
                "tool_input": {
                    "subject": "Meta task",
                    "metadata": {"type": "epic", "color": "red"},
                },
                "tool_result": "Task #5 created successfully: Meta task",
            },
        )
        _run_hook(
            payload={
                "tool_name": "TaskUpdate",
                "tool_input": {
                    "taskId": "5",
                    "metadata": {"color": "blue", "priority": "high"},
                },
                "tool_result": "Updated task #5 metadata",
            },
        )
        plan = _read_plan_yaml()
        task = next(t for t in plan["tasks"] if t["id"] == "5")
        assert task["metadata"]["type"] == "epic"
        assert task["metadata"]["color"] == "blue"
        assert task["metadata"]["priority"] == "high"

    def test_all_completed_sets_plan_completed(self) -> None:
        for i in range(1, 3):
            _run_hook(
                payload={
                    "tool_name": "TaskUpdate",
                    "tool_input": {"taskId": str(i), "status": "completed"},
                    "tool_result": f"Updated task #{i} status",
                },
            )
        plan = _read_plan_yaml()
        assert plan["plan"]["status"] == "completed"
        assert "completed_at" in plan["plan"]


class TestEdgeCases:
    @pytest.mark.parametrize("stdin", ["", "{invalid json}"], ids=["empty", "malformed"])
    def test_unreadable_stdin_exits_cleanly(self, stdin: str) -> None:
        assert _run_hook_raw(stdin=stdin).returncode == 0

    @pytest.mark.parametrize("stdin", ["", "{invalid json}"], ids=["empty", "malformed"])
    def test_unreadable_stdin_writes_no_plan(self, stdin: str) -> None:
        _run_hook_raw(stdin=stdin)

        assert _plan_files() == []

    def test_lost_in_progress_task_is_restored_by_the_hook(self) -> None:
        """GH-1514 end to end: a mirror missing the task heals on its update."""
        _seed_task(task_id=1)

        _run_hook(
            payload={
                "tool_name": "TaskUpdate",
                "tool_input": {"taskId": "9", "status": "in_progress"},
                "tool_result": "Updated task #9 status",
            },
        )

        plan = _read_plan_yaml()
        assert [(t["id"], t["status"]) for t in plan["tasks"]] == [
            ("1", "pending"),
            ("9", "in_progress"),
        ]

    def test_missing_tool_result(self) -> None:
        _run_hook(
            payload={
                "tool_name": "TaskCreate",
                "tool_input": {"subject": "No result"},
                "tool_result": "",
            },
        )
        assert len(_plan_files()) == 0

    def test_unknown_tool_name(self) -> None:
        _run_hook(
            payload={
                "tool_name": "SomeOtherTool",
                "tool_input": {},
                "tool_result": "",
            },
        )
        assert len(_plan_files()) == 0

    def test_update_nonexistent_task(self) -> None:
        _run_hook(
            payload={
                "tool_name": "TaskCreate",
                "tool_input": {"subject": "Task 1"},
                "tool_result": "Task #1 created successfully: Task 1",
            },
        )
        result = _run_hook(
            payload={
                "tool_name": "TaskUpdate",
                "tool_input": {"taskId": "99", "status": "completed"},
                "tool_result": "Updated task #99 status",
            },
        )
        assert result.returncode == 0
        plan = _read_plan_yaml()
        assert len(plan["tasks"]) == 1
        assert plan["tasks"][0]["status"] == "pending"

    def test_last_synced_updates(self) -> None:
        _run_hook(
            payload={
                "tool_name": "TaskCreate",
                "tool_input": {"subject": "First"},
                "tool_result": "Task #1 created successfully: First",
            },
        )
        plan1 = _read_plan_yaml()
        synced1 = plan1["plan"]["last_synced"]

        _run_hook(
            payload={
                "tool_name": "TaskUpdate",
                "tool_input": {"taskId": "1", "status": "completed"},
                "tool_result": "Updated task #1 status",
            },
        )
        plan2 = _read_plan_yaml()
        synced2 = plan2["plan"]["last_synced"]
        assert synced2 >= synced1


def _run_cli(
    *args: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(HOOK), *args],
        capture_output=True,
        text=True,
        timeout=10,
        env=os.environ.copy(),
        cwd=_sandbox(),
    )


def _seed_task(task_id: int = 1) -> None:
    _run_hook(
        payload={
            "tool_name": "TaskCreate",
            "tool_input": {"subject": f"Task {task_id}"},
            "tool_result": f"Task #{task_id} created successfully: Task {task_id}",
        },
    )


class TestSetContext:
    def test_stores_simple_key_value(self) -> None:
        _seed_task()
        result = _run_cli("--set-context", "work_type=feature")
        assert result.returncode == 0
        plan = _read_plan_yaml()
        assert plan["plan"]["context"]["work_type"] == "feature"

    def test_stores_json_value(self) -> None:
        _seed_task()
        result = _run_cli("--set-context", 'tickets=["GH-1","GH-2"]')
        assert result.returncode == 0
        plan = _read_plan_yaml()
        assert plan["plan"]["context"]["tickets"] == ["GH-1", "GH-2"]

    def test_stores_dict_value(self) -> None:
        _seed_task()
        result = _run_cli(
            "--set-context",
            'routing_table={"commit":"Skill(git-commit)"}',
        )
        assert result.returncode == 0
        plan = _read_plan_yaml()
        assert plan["plan"]["context"]["routing_table"]["commit"] == "Skill(git-commit)"

    def test_preserves_existing_tasks(self) -> None:
        _seed_task()
        _run_cli("--set-context", "work_type=bugfix")
        plan = _read_plan_yaml()
        assert len(plan["tasks"]) == 1
        assert plan["tasks"][0]["subject"] == "Task 1"

    def test_multiple_key_values_in_one_call(self) -> None:
        _seed_task()
        result = _run_cli(
            "--set-context",
            "work_type=feature",
            'tickets=["GH-482"]',
            "gathered_summary=Working on plan persistence",
        )
        assert result.returncode == 0
        plan = _read_plan_yaml()
        assert plan["plan"]["context"]["work_type"] == "feature"
        assert plan["plan"]["context"]["tickets"] == ["GH-482"]
        assert plan["plan"]["context"]["gathered_summary"] == "Working on plan persistence"

    def test_creates_plan_if_none_exists(self) -> None:
        result = _run_cli("--set-context", "work_type=investigation")
        assert result.returncode == 0
        plan = _read_plan_yaml()
        assert plan["plan"]["context"]["work_type"] == "investigation"

    def test_invalid_argument_exits_with_error(self) -> None:
        result = _run_cli("--set-context", "no-equals-sign")
        assert result.returncode == 1
        assert "Invalid argument" in result.stderr


class TestArchive:
    def test_archives_completed_plan(self) -> None:
        _seed_task()
        _run_hook(
            payload={
                "tool_name": "TaskUpdate",
                "tool_input": {"taskId": "1", "status": "completed"},
                "tool_result": "Updated task #1 status",
            },
        )
        result = _run_cli("--archive")
        assert result.returncode == 0
        assert "Archived plan to" in result.stdout
        assert len(_plan_files()) == 0

    def test_archive_creates_archive_directory(self) -> None:
        _seed_task()
        archive_dir = _sandbox() / ".claude" / "session" / "archive"
        _run_cli("--archive")
        assert len(list(archive_dir.glob("plan-*.yaml"))) == 1

    def test_archive_without_plan_exits_cleanly(self) -> None:
        result = _run_cli("--archive")
        assert result.returncode == 0
        assert "No plan file" in result.stdout


class TestLiveCheckoutIsolation:
    """GH-1514: running these tests must never touch the checkout's own plan."""

    @staticmethod
    def _live_session_state() -> tuple[bytes | None, list[str]]:
        session = _REPO_ROOT / ".claude" / "session"
        plan = session / "plan.yaml"
        archive = session / "archive"
        return (
            plan.read_bytes() if plan.exists() else None,
            sorted(p.name for p in archive.glob("*")) if archive.exists() else [],
        )

    def test_hook_and_archive_leave_the_live_session_untouched(self) -> None:
        before = self._live_session_state()

        _seed_task()
        _run_cli("--archive")

        assert self._live_session_state() == before

    def test_hook_writes_into_the_sandbox(self) -> None:
        _seed_task()

        assert _plan_path().exists()


class TestYamlRoundtrip:
    def test_plan_file_is_yaml(self) -> None:
        _run_hook(
            payload={
                "tool_name": "TaskCreate",
                "tool_input": {"subject": "YAML test"},
                "tool_result": "Task #1 created successfully: YAML test",
            },
        )
        files = _plan_files()
        assert len(files) == 1
        content = files[0].read_text()
        assert content.startswith("plan:\n")
        assert "tasks:\n" in content

    def test_plan_file_in_repo_claude_session(self) -> None:
        _run_hook(
            payload={
                "tool_name": "TaskCreate",
                "tool_input": {"subject": "Location test"},
                "tool_result": "Task #1 created successfully: Location test",
            },
        )
        files = _plan_files()
        assert len(files) == 1
        assert ".claude/session/plan.yaml" in str(files[0])

    def test_json_summary_mode(self) -> None:
        _run_hook(
            payload={
                "tool_name": "TaskCreate",
                "tool_input": {"subject": "Summary test"},
                "tool_result": "Task #1 created successfully: Summary test",
            },
        )
        result = subprocess.run(
            [str(HOOK), "--json-summary"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=_sandbox(),
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["plan"]["status"] == "in_progress"
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["subject"] == "Summary test"
