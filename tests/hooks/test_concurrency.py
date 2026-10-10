"""Concurrency tests for shared state file writers (GH-77).

Exercises two or more simulated concurrent writers against the
task-plan-sync hook to verify the file_lock around the
load→mutate→save cycle prevents data loss when worktrees or
parallel agents fire TaskCreate hooks simultaneously.

The writers run in ``sandbox_repo`` (GH-1514): run in the checkout
under test, they and the old cleanup fixture rewrote and then deleted
that checkout's live task mirror.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = _REPO_ROOT / "hooks" / "scripts" / "task-plan-sync.py"


class TestParallelTaskCreate:
    def test_concurrent_writers_preserve_all_tasks(self, sandbox_repo: Path) -> None:
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
                cwd=sandbox_repo,
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
            cwd=sandbox_repo,
        )
        plan = json.loads(summary.stdout)
        ids = sorted(int(t["id"]) for t in plan["tasks"])
        assert ids == writers, (
            f"expected all {len(writers)} tasks to survive concurrent writes, got {ids}"
        )
