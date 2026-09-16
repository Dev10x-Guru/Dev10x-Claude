"""GH-1339 / GH-1366: what the gate does when work remains.

GH-1339 ended the demand for an ``AskUserQuestion`` on every turn. A
session holding a pending task was being told to ask the supervisor
about work it had already been told to do, and across five days of
audit records a block was the gate's single most common outcome.

GH-1366 corrected the *direction* of that fix. A Stop hook's ``block``
means **do not stop** — the turn continues and the steer becomes its
next instruction. Reading "auto-advance" as "let the turn end quietly"
produced ``block=False`` on open work, which removed the only mechanism
that keeps an agent going; a session with real pending tasks then
stopped at a "natural reporting point" and nothing objected.

So open work continues the turn. What stops the gate firing on every
turn is structural: GH-149 keeps a terminal ``Verify acceptance
criteria`` task open until the supervisor signs off, so "something is
open" is nearly always true. The discriminator is whether anything
*besides* that gate is open.
"""

from __future__ import annotations

from pathlib import Path

from dev10x.hooks.stop_verdict import (
    StopSignal,
    TaskSignal,
    auto_advances,
    decide,
    task_signal,
)

from .conftest import DEPLETED_PLAN, PENDING_PLAN
from .test_stop_verdict import _assistant, _text
from .test_stop_verdict import _transcript as _write_transcript

_TERMINAL_ONLY = {"tasks": [{"subject": "Verify acceptance criteria", "status": "pending"}]}
_WORK_AND_TERMINAL = {
    "tasks": [
        {"subject": "Monitor CI", "status": "pending"},
        {"subject": "Verify acceptance criteria", "status": "pending"},
    ]
}


def _transcript(*, tmp_path: Path, closing: str) -> str:
    """One turn: the supervisor speaks, the agent closes with ``closing``.

    The entry shapes and the JSONL writing come from the sibling module
    rather than being restated here — that knowledge already had three
    copies in this package.
    """
    return _write_transcript(
        tmp_path=tmp_path,
        entries=[
            {"type": "user", "message": {"role": "user", "content": "carry on"}},
            _assistant(blocks=[_text(text=closing)]),
        ],
    )


class TestOpenWorkContinuesTheTurn:
    def test_a_pending_task_keeps_the_turn_alive(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        verdict = decide(
            data={
                "session_id": "adv1",
                "transcript_path": _transcript(tmp_path=tmp_path, closing="Committed."),
            },
            plan=PENDING_PLAN,
        )

        assert verdict.block is True
        assert verdict.signal == StopSignal.CONTINUE

    def test_the_steer_names_the_next_task(self, tmp_path: Path, isolated_markers: Path) -> None:
        """The plan already says what comes next, so the steer says it too."""
        verdict = decide(
            data={
                "session_id": "adv2",
                "transcript_path": _transcript(tmp_path=tmp_path, closing="Committed."),
            },
            plan=PENDING_PLAN,
        )

        assert "Monitor CI" in verdict.reason

    def test_the_steer_never_asks(self, tmp_path: Path, isolated_markers: Path) -> None:
        """There is no decision here to hand anyone."""
        verdict = decide(
            data={
                "session_id": "adv3",
                "transcript_path": _transcript(tmp_path=tmp_path, closing="Committed."),
            },
            plan=PENDING_PLAN,
        )

        assert "AskUserQuestion" not in verdict.reason

    def test_a_progress_report_is_not_a_stopping_point(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        """The failure GH-1366 was filed for, in its observed shape."""
        verdict = decide(
            data={
                "session_id": "adv4",
                "transcript_path": _transcript(
                    tmp_path=tmp_path,
                    closing="I'm at a natural reporting point. Here's where things stand.",
                ),
            },
            plan=_WORK_AND_TERMINAL,
        )

        assert verdict.block is True
        assert verdict.signal == StopSignal.CONTINUE

    def test_a_phase_boundary_continues_like_any_open_work(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        """`resolve_gate` owns plan gates; this one just keeps the turn alive."""
        verdict = decide(
            data={
                "session_id": "adv5",
                "transcript_path": _transcript(tmp_path=tmp_path, closing="Phase 3 is done."),
            },
            plan={
                "tasks": [
                    {"subject": "Phase 3: Build work plan", "status": "completed"},
                    {"subject": "Phase 4: Execute plan", "status": "pending"},
                ]
            },
        )

        assert verdict.signal == StopSignal.CONTINUE
        assert "Phase 4: Execute plan" in verdict.reason


class TestTheTerminalGateIsNotWork:
    """GH-149 keeps it open, so it cannot mean "keep working"."""

    def test_only_the_terminal_task_ends_the_turn(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        verdict = decide(
            data={
                "session_id": "adv6",
                "transcript_path": _transcript(tmp_path=tmp_path, closing="Ready for sign-off."),
            },
            plan=_TERMINAL_ONLY,
        )

        assert verdict.block is False
        assert verdict.signal == StopSignal.AWAITING_SUPERVISOR

    def test_work_alongside_the_terminal_task_still_continues(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        verdict = decide(
            data={
                "session_id": "adv7",
                "transcript_path": _transcript(tmp_path=tmp_path, closing="Committed."),
            },
            plan=_WORK_AND_TERMINAL,
        )

        assert verdict.signal == StopSignal.CONTINUE
        assert "Monitor CI" in verdict.reason

    def test_the_terminal_task_is_told_apart_by_the_domain_definition(self) -> None:
        """One definition, shared with the GH-149 PreToolUse guard."""
        signal = task_signal(plan=_WORK_AND_TERMINAL)

        assert signal.actionable_subjects == ("Monitor CI",)
        assert signal.has_open_work is True
        assert signal.awaits_supervisor is False


class TestADeferralIsNotADecision:
    """The supervisor's ruling: "shall I push?" has an obvious answer."""

    def test_a_prose_deferral_does_not_change_the_verdict(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        verdict = decide(
            data={
                "session_id": "adv8",
                "transcript_path": _transcript(
                    tmp_path=tmp_path, closing="say go and I'll push it."
                ),
            },
            plan=PENDING_PLAN,
        )

        assert verdict.signal == StopSignal.CONTINUE


class TestADepletedListAsksToStandDown:
    def test_a_completed_task_list_asks_to_stand_down(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        """Out of work is the one state where the decision is the supervisor's."""
        verdict = decide(
            data={
                "session_id": "adv9",
                "transcript_path": _transcript(tmp_path=tmp_path, closing="Everything is merged."),
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
                "session_id": "adv10",
                "transcript_path": _transcript(tmp_path=tmp_path, closing="All done."),
            },
            plan=DEPLETED_PLAN,
        )

        assert "(Recommended)" in verdict.reason
        assert "On standby" in verdict.reason

    def test_the_steer_sends_the_agent_back_to_the_plan_first(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        """A depleted task list is not an exhausted plan."""
        verdict = decide(
            data={
                "session_id": "adv11",
                "transcript_path": _transcript(
                    tmp_path=tmp_path, closing="That was the last one."
                ),
            },
            plan=DEPLETED_PLAN,
        )
        reason = verdict.reason.replace("\n", " ")

        assert "Re-read the plan" in reason
        assert "low on context is not a reason to ask" in reason

    def test_the_steer_tells_a_subagent_not_to_ask_the_human(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        """The fallback for when `subagent_signal` misses."""
        verdict = decide(
            data={
                "session_id": "adv12",
                "transcript_path": _transcript(tmp_path=tmp_path, closing="All four are done."),
            },
            plan=DEPLETED_PLAN,
        )

        assert "orchestrator" in verdict.reason
        assert "whether you may exit" in verdict.reason


class TestAnAbsentListIsNotADepletedOne:
    """GH-1055: the task tools ship by default only on older models.

    A session without them never populates ``plan.tasks``, so emptiness
    there is the absence of a mechanism, not evidence that the work is
    finished — `essentials.md` says so in as many words.
    """

    def test_no_plan_at_all_ends_the_turn(self, tmp_path: Path, isolated_markers: Path) -> None:
        verdict = decide(
            data={
                "session_id": "adv13",
                "transcript_path": _transcript(tmp_path=tmp_path, closing="Committed."),
            },
            plan=None,
        )

        assert verdict.block is False
        assert verdict.signal == StopSignal.NO_TASK_LIST

    def test_a_plan_carrying_no_tasks_ends_the_turn(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        verdict = decide(
            data={
                "session_id": "adv14",
                "transcript_path": _transcript(tmp_path=tmp_path, closing="Committed."),
            },
            plan={"context": {}},
        )

        assert verdict.signal == StopSignal.NO_TASK_LIST

    def test_an_absent_list_is_told_apart_from_a_depleted_one(self) -> None:
        assert task_signal(plan=None).has_task_list is False
        assert task_signal(plan=DEPLETED_PLAN).has_task_list is True


class TestTheRuleIsAPureFunction:
    def test_actionable_work_keeps_the_turn_alive(self) -> None:
        signal = TaskSignal(open_subjects=("Monitor CI",), has_task_list=True)

        assert auto_advances(signal=signal) is True

    def test_a_depleted_list_does_not(self) -> None:
        assert auto_advances(signal=TaskSignal(has_task_list=True)) is False

    def test_the_terminal_gate_alone_does_not(self) -> None:
        signal = TaskSignal(open_subjects=("Verify acceptance criteria",), has_task_list=True)

        assert auto_advances(signal=signal) is False
        assert signal.awaits_supervisor is True


class TestTheSignalsAreLegible:
    def test_continue_reprs_as_a_member(self) -> None:
        assert repr(StopSignal.CONTINUE) == "StopSignal.CONTINUE"

    def test_awaiting_supervisor_reprs_as_a_member(self) -> None:
        assert repr(StopSignal.AWAITING_SUPERVISOR) == "StopSignal.AWAITING_SUPERVISOR"

    def test_no_task_list_reprs_as_a_member(self) -> None:
        assert repr(StopSignal.NO_TASK_LIST) == "StopSignal.NO_TASK_LIST"
