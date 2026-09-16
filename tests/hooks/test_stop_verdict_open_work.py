"""GH-1339: open work auto-advances instead of demanding a widget.

The gate asked for an ``AskUserQuestion`` on every turn, so a session
holding a pending task was told to ask the supervisor about work it had
already been told to do. Across five days of audit records a block was
the gate's single most common outcome.

The rule that replaces it comes from the pre-collapse friction ladder,
where ``guided`` meant "block **with a recommendation**" and ``adaptive``
auto-selected that recommendation: a gate fires only where there is no
recommended next action. Open work *is* the recommended next action.

One carve-out survives an open task list, because it is not a
confirmation prompt — a closing sentence that defers a decision in prose
is a true question, asked badly.
"""

from __future__ import annotations

import json
from pathlib import Path

from dev10x.hooks.stop_verdict import (
    StopSignal,
    TaskSignal,
    auto_advances,
    decide,
    task_signal,
)

from .conftest import DEPLETED_PLAN, PENDING_PLAN


def _assistant(*, text: str) -> dict:
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


def _transcript(*, tmp_path: Path, closing: str) -> str:
    entries = [
        {"type": "user", "message": {"role": "user", "content": "carry on"}},
        _assistant(text=closing),
    ]
    path = tmp_path / "transcript.jsonl"
    path.write_text("\n".join(json.dumps(entry) for entry in entries), encoding="utf-8")
    return str(path)


class TestOpenWorkEndsTheTurn:
    def test_a_pending_task_is_not_a_reason_to_ask(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        verdict = decide(
            data={
                "session_id": "adv1",
                "transcript_path": _transcript(tmp_path=tmp_path, closing="Committed."),
            },
            plan=PENDING_PLAN,
        )

        assert verdict.block is False
        assert verdict.signal == StopSignal.OPEN_WORK

    def test_in_progress_work_advances_too(self, tmp_path: Path, isolated_markers: Path) -> None:
        verdict = decide(
            data={
                "session_id": "adv2",
                "transcript_path": _transcript(tmp_path=tmp_path, closing="Pushed."),
            },
            plan={"tasks": [{"subject": "Wait out CI", "status": "in_progress"}]},
        )

        assert verdict.signal == StopSignal.OPEN_WORK

    def test_a_phase_boundary_advances_like_any_open_work(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        """A pending next phase is open work, and `resolve_gate` owns plan gates.

        The hook deciding this a second time is the over-firing GH-1339
        is about — a phase boundary always implies a pending phase, so
        treating it as a hard gate would exempt the commonest shape of
        open work from the rule.
        """
        verdict = decide(
            data={
                "session_id": "adv3",
                "transcript_path": _transcript(tmp_path=tmp_path, closing="Phase 3 is done."),
            },
            plan={
                "tasks": [
                    {"subject": "Phase 3: Build work plan", "status": "completed"},
                    {"subject": "Phase 4: Execute plan", "status": "pending"},
                ]
            },
        )

        assert verdict.block is False
        assert verdict.signal == StopSignal.OPEN_WORK


class TestATrueQuestionStillAsks:
    def test_a_prose_deferral_still_blocks(self, tmp_path: Path, isolated_markers: Path) -> None:
        """The agent held a decision back; open work does not excuse that."""
        verdict = decide(
            data={
                "session_id": "adv4",
                "transcript_path": _transcript(
                    tmp_path=tmp_path, closing="say go and I'll push it."
                ),
            },
            plan=PENDING_PLAN,
        )

        assert verdict.block is True

    def test_a_completed_task_list_asks_to_stand_down(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        """Out of work is the one state where the decision is the supervisor's."""
        verdict = decide(
            data={
                "session_id": "adv5",
                "transcript_path": _transcript(tmp_path=tmp_path, closing="Everything is merged."),
            },
            plan=DEPLETED_PLAN,
        )

        assert verdict.block is True
        assert "stand down" in verdict.reason.lower()

    def test_a_deferral_on_a_depleted_list_still_asks_to_stand_down(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        """Both blocking conditions at once resolve to the stand-down steer.

        The steer does not separately acknowledge the deferral, which is
        right — standing down subsumes it — but it is worth pinning, so
        a later edit cannot change it silently.
        """
        verdict = decide(
            data={
                "session_id": "adv9",
                "transcript_path": _transcript(
                    tmp_path=tmp_path, closing="All merged. Shall I close the milestone?"
                ),
            },
            plan=DEPLETED_PLAN,
        )

        assert verdict.block is True
        assert "stand down" in verdict.reason.lower()

    def test_the_surviving_gate_carries_a_recommendation(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        """Pre-collapse `guided` blocked WITH a recommendation, never open-endedly."""
        verdict = decide(
            data={
                "session_id": "adv6",
                "transcript_path": _transcript(tmp_path=tmp_path, closing="All done."),
            },
            plan=DEPLETED_PLAN,
        )

        assert "(Recommended)" in verdict.reason
        assert "On standby" in verdict.reason


class TestAnAbsentListIsNotADepletedOne:
    """GH-1055: the task tools ship by default only on older models.

    A session without them never populates ``plan.tasks``, so emptiness
    there is the absence of a mechanism, not evidence that the work is
    finished — `essentials.md` says so in as many words. Reading the two
    as the same state would block every turn of every such session,
    which is the very over-firing GH-1339 exists to end.
    """

    def test_no_plan_at_all_advances(self, tmp_path: Path, isolated_markers: Path) -> None:
        verdict = decide(
            data={
                "session_id": "adv7",
                "transcript_path": _transcript(tmp_path=tmp_path, closing="Committed."),
            },
            plan=None,
        )

        assert verdict.block is False
        assert verdict.signal == StopSignal.NO_TASK_LIST

    def test_a_plan_carrying_no_tasks_advances(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        verdict = decide(
            data={
                "session_id": "adv8",
                "transcript_path": _transcript(tmp_path=tmp_path, closing="Committed."),
            },
            plan={"context": {}},
        )

        assert verdict.signal == StopSignal.NO_TASK_LIST

    def test_an_absent_list_is_told_apart_from_a_depleted_one(self) -> None:
        assert task_signal(plan=None).has_task_list is False
        assert task_signal(plan=DEPLETED_PLAN).has_task_list is True


class TestTheRuleIsAPureFunction:
    def test_a_depleted_list_does_not_advance(self) -> None:
        signal = TaskSignal(has_task_list=True)

        assert auto_advances(signal=signal, closing="Done.") is False

    def test_open_work_advances(self) -> None:
        signal = TaskSignal(open_subjects=("Monitor CI",), has_task_list=True)

        assert auto_advances(signal=signal, closing="Done.") is True

    def test_an_absent_list_advances(self) -> None:
        assert auto_advances(signal=TaskSignal(), closing="Done.") is True

    def test_a_deferral_overrides_open_work(self) -> None:
        signal = TaskSignal(open_subjects=("Monitor CI",), has_task_list=True)

        assert auto_advances(signal=signal, closing="Shall I push?") is False

    def test_a_deferral_overrides_an_absent_list_too(self) -> None:
        assert auto_advances(signal=TaskSignal(), closing="Shall I push?") is False


class TestTheSignalIsLegible:
    def test_open_work_reprs_as_a_member(self) -> None:
        assert repr(StopSignal.OPEN_WORK) == "StopSignal.OPEN_WORK"

    def test_no_task_list_reprs_as_a_member(self) -> None:
        assert repr(StopSignal.NO_TASK_LIST) == "StopSignal.NO_TASK_LIST"
