"""GH-1569: the Stop gate still sees open tasks after task management left core.

B6 ships the task skills as ``dev10x-tasks``. The task list reaches the
Stop hook only through ``plan.yaml``: the ``task-plan-sync`` hook that
``hooks/hooks.d/tasks.json`` registers writes it, and core's Stop hook
reads it back through ``dev10x.core.plan_mirror`` (GH-1530). A break on
either side would leave every session judged on an empty list, so these
tests run the registered writer as a subprocess and hand its output to
the real Stop wiring.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from dev10x.core.config.hook_fragments import hook_files, merged_hook_entries
from dev10x.core.hooks import session_dispatch
from dev10x.core.hooks.session_dispatch import build_stop_verdict
from dev10x.core.hooks.stop_verdict import StopSignal
from dev10x.core.subprocess_utils import get_plugin_root

from .test_stop_verdict import _assistant, _text
from .test_stop_verdict import _transcript as _write_transcript

PLUGIN_ROOT = get_plugin_root()
TASKS_FRAGMENT = PLUGIN_ROOT / "hooks" / "hooks.d" / "tasks.json"
PLAN_SYNC_MATCHER = "TaskCreate|TaskUpdate"


def _plan_sync_script() -> Path:
    document = json.loads(TASKS_FRAGMENT.read_text())
    (command,) = [
        hook["command"]
        for group in document["hooks"]["PostToolUse"]
        if group["matcher"] == PLAN_SYNC_MATCHER
        for hook in group["hooks"]
    ]
    return Path(command.split()[-1].replace("$CLAUDE_PLUGIN_ROOT", str(PLUGIN_ROOT)))


def _sync(*, repo: Path, payload: dict) -> None:
    subprocess.run(
        [str(_plan_sync_script())],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env=os.environ.copy(),
        cwd=repo,
        check=True,
    )


def _create(*, repo: Path, task_id: str, subject: str) -> None:
    _sync(
        repo=repo,
        payload={
            "tool_name": "TaskCreate",
            "tool_input": {"subject": subject, "description": subject},
            "tool_result": f"Task #{task_id} created successfully: {subject}",
        },
    )


def _complete(*, repo: Path, task_id: str) -> None:
    _sync(
        repo=repo,
        payload={
            "tool_name": "TaskUpdate",
            "tool_input": {"taskId": task_id, "status": "completed"},
            "tool_result": f"Updated task #{task_id} status",
        },
    )


@pytest.fixture
def recorded(sandbox_repo: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    captured: dict[str, str] = {}

    def _capture(*, rule_id: str, reason: str, extra: dict[str, str] | None = None) -> None:
        captured.update(rule_id=rule_id, reason=reason, **(extra or {}))

    monkeypatch.setattr(session_dispatch, "_get_toplevel", lambda: str(sandbox_repo))
    monkeypatch.setattr(session_dispatch, "_uncommitted_paths", lambda: ())
    monkeypatch.setattr(session_dispatch, "set_decision_attribution", _capture)
    return captured


@pytest.fixture
def transcript(tmp_path: Path) -> str:
    return _write_transcript(
        tmp_path=tmp_path,
        entries=[
            {"type": "user", "message": {"role": "user", "content": "carry on"}},
            _assistant(blocks=[_text(text="Committed.")]),
        ],
    )


@pytest.fixture
def open_work_verdict(
    sandbox_repo: Path,
    recorded: dict[str, str],
    transcript: str,
    isolated_markers: Path,
) -> tuple[object, str]:
    _create(repo=sandbox_repo, task_id="1", subject="Monitor CI")
    _create(repo=sandbox_repo, task_id="2", subject="Verify acceptance criteria")
    verdict = build_stop_verdict(data={"session_id": "gh1569a", "transcript_path": transcript})
    return verdict, recorded["signal"]


@pytest.fixture
def depleted_verdict(
    sandbox_repo: Path,
    recorded: dict[str, str],
    transcript: str,
    isolated_markers: Path,
) -> tuple[object, str]:
    _create(repo=sandbox_repo, task_id="1", subject="Monitor CI")
    _complete(repo=sandbox_repo, task_id="1")
    verdict = build_stop_verdict(data={"session_id": "gh1569b", "transcript_path": transcript})
    return verdict, recorded["signal"]


class TestTheRegistrationStaysWithCore:
    def test_core_manifest_loads_the_tasks_fragment(self) -> None:
        manifest = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text())

        assert "./hooks/hooks.d/tasks.json" in manifest["hooks"]

    def test_the_fragment_is_discovered(self) -> None:
        assert TASKS_FRAGMENT in hook_files(plugin_root=PLUGIN_ROOT)

    def test_the_satellite_registers_no_second_copy(self) -> None:
        manifest = json.loads(
            (PLUGIN_ROOT / "plugins" / "tasks" / ".claude-plugin" / "plugin.json").read_text()
        )

        assert "hooks" not in manifest

    def test_writer_and_reader_are_both_registered(self) -> None:
        commands = {
            (event, matcher, Path(command.split()[-1]).name)
            for event, matcher, command, _ in merged_hook_entries(plugin_root=PLUGIN_ROOT)
        }

        assert {
            ("PostToolUse", PLAN_SYNC_MATCHER, "task-plan-sync.py"),
            ("Stop", "*", "session-stop.py"),
        } <= commands


class TestTheStopGateReadsTheWrittenPlan:
    def test_open_tasks_end_the_turn_as_open_work(
        self, open_work_verdict: tuple[object, str]
    ) -> None:
        assert open_work_verdict == (None, StopSignal.OPEN_WORK)

    def test_a_completed_list_is_seen_as_depleted(
        self, depleted_verdict: tuple[object, str]
    ) -> None:
        verdict, signal = depleted_verdict

        assert (verdict is not None, signal) == (True, StopSignal.BLOCKED)
