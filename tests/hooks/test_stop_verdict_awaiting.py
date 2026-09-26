"""A turn may end while every open task waits on dispatched work (GH-1464).

With each open task blocked on running fanout children there was no
compliant move: the verdict demanded continuation, and
``watch-loop-handrolled`` forbade every way of waiting in-turn. A task
tagged ``awaiting`` is parked, not actionable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.hooks.stop_verdict import AWAITING_KEY, StopSignal, decide, task_signal

VERIFY = "Verify acceptance criteria"


def _task(*, subject: str, status: str = "in_progress", awaiting: object = None) -> dict:
    task: dict = {"subject": subject, "status": status}
    if awaiting is not None:
        task["metadata"] = {AWAITING_KEY: awaiting}
    return task


@pytest.fixture()
def transcript(tmp_path: Path) -> str:
    path = tmp_path / "transcript.jsonl"
    entries = [
        {"type": "user", "message": {"role": "user", "content": "run the wave"}},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Four children in flight."}],
            },
        },
    ]
    path.write_text("\n".join(json.dumps(entry) for entry in entries), encoding="utf-8")
    return str(path)


class TestTaskSignal:
    def test_an_awaiting_task_is_not_actionable(self) -> None:
        signal = task_signal(plan={"tasks": [_task(subject="Child 1", awaiting="subagent")]})

        assert signal.actionable_subjects == ()
        assert signal.awaits_dispatched_work is True

    def test_a_cleared_tag_makes_the_task_actionable_again(self) -> None:
        cleared = {"subject": "Child 1", "status": "in_progress", "metadata": {"awaiting": None}}

        signal = task_signal(plan={"tasks": [cleared]})

        assert signal.actionable_subjects == ("Child 1",)
        assert signal.awaits_dispatched_work is False

    def test_non_dict_metadata_is_not_a_tag(self) -> None:
        odd = {"subject": "Child 1", "status": "pending", "metadata": "awaiting"}

        assert task_signal(plan={"tasks": [odd]}).awaiting_subjects == ()

    def test_a_completed_awaiting_task_is_not_counted(self) -> None:
        done = _task(subject="Child 1", status="completed", awaiting="subagent")

        assert task_signal(plan={"tasks": [done]}).awaiting_subjects == ()


class TestDecide:
    def test_every_task_awaiting_ends_the_turn(
        self,
        transcript: str,
        isolated_markers: Path,
    ) -> None:
        plan = {
            "tasks": [
                _task(subject="Child 1", awaiting="subagent"),
                _task(subject="Child 2", awaiting=True),
                _task(subject=VERIFY, status="pending"),
            ]
        }

        verdict = decide(data={"session_id": "aw1", "transcript_path": transcript}, plan=plan)

        assert verdict.block is False
        assert verdict.signal == StopSignal.AWAITING_SUBAGENTS

    def test_a_dirty_tree_does_not_block_a_mid_wave_turn(
        self,
        transcript: str,
        isolated_markers: Path,
    ) -> None:
        plan = {"tasks": [_task(subject="Child 1", awaiting="subagent")]}

        verdict = decide(
            data={"session_id": "aw2", "transcript_path": transcript},
            plan=plan,
            dirty=("notes.md",),
        )

        assert verdict.signal == StopSignal.AWAITING_SUBAGENTS

    def test_one_actionable_task_still_continues_the_turn(
        self,
        transcript: str,
        isolated_markers: Path,
    ) -> None:
        plan = {
            "tasks": [
                _task(subject="Child 1", awaiting="subagent"),
                _task(subject="Draft release notes", status="pending"),
            ]
        }

        verdict = decide(data={"session_id": "aw3", "transcript_path": transcript}, plan=plan)

        assert verdict.block is True
        assert verdict.signal == StopSignal.CONTINUE
        assert "Draft release notes" in verdict.reason

    def test_the_continue_steer_names_the_tag(
        self,
        transcript: str,
        isolated_markers: Path,
    ) -> None:
        plan = {"tasks": [_task(subject="Monitor wave")]}

        verdict = decide(data={"session_id": "aw4", "transcript_path": transcript}, plan=plan)

        assert '{"awaiting": "subagent"}' in verdict.reason
