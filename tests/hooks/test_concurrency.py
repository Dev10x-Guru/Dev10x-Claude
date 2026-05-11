"""Concurrency tests for shared state file writers (GH-77).

Exercises two or more simulated concurrent writers against the
task-plan-sync hook to verify the file_lock around the
load→mutate→save cycle prevents data loss when worktrees or
parallel agents fire TaskCreate hooks simultaneously.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = _REPO_ROOT / "hooks" / "scripts" / "task-plan-sync.py"


def _plan_path() -> Path:
    toplevel = subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
    ).strip()
    return Path(toplevel) / ".claude" / "session" / "plan.yaml"


def _cleanup_plan() -> None:
    plan = _plan_path()
    if plan.exists():
        plan.unlink()
    lock = plan.with_suffix(plan.suffix + ".lock")
    if lock.exists():
        lock.unlink()
    session_dir = plan.parent
    if session_dir.exists():
        try:
            session_dir.rmdir()
        except OSError:
            pass


@pytest.fixture(autouse=True)
def _clean_plan():
    _cleanup_plan()
    yield
    _cleanup_plan()


class TestParallelTaskCreate:
    def test_concurrent_writers_preserve_all_tasks(self) -> None:
        writers = list(range(1, 9))
        processes: list[tuple[int, subprocess.Popen[str]]] = []
        for task_id in writers:
            payload = json.dumps(
                {
                    "tool_name": "TaskCreate",
                    "tool_input": {"subject": f"Task {task_id}"},
                    "tool_result": (f"Task #{task_id} created successfully: Task {task_id}"),
                }
            )
            proc = subprocess.Popen(
                [str(HOOK)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={**os.environ},
            )
            proc.stdin.write(payload)
            proc.stdin.close()
            processes.append((task_id, proc))

        for task_id, proc in processes:
            proc.wait(timeout=15)
            assert proc.returncode == 0, (
                f"writer {task_id} exited {proc.returncode}; stderr={proc.stderr.read()}"
            )

        summary = subprocess.run(
            [str(HOOK), "--json-summary"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        plan = json.loads(summary.stdout)
        ids = sorted(int(t["id"]) for t in plan["tasks"])
        assert ids == writers, (
            f"expected all {len(writers)} tasks to survive concurrent writes, got {ids}"
        )
