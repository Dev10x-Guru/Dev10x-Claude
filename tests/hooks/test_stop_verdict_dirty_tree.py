"""GH-1365: a depleted task list with a dirty tree is not done.

"The list is empty" is a claim about *tracking*. "The tree is clean" is
a claim about the *work*. They come apart exactly when an agent finishes
editing and forgets the commit — which is the case worth catching, and
the one the supervisor named: if a session declares its work done but
git is not clean, the agent is not done.

**The delicacy is attribution.** A session and the subagents it
dispatches share one worktree, so uncommitted changes visible here may
belong to a concurrent session. Nothing at Stop time can settle whose
they are: uncommitted changes carry no author, and the transcript window
is deliberately one turn. So the rule does not try to decide — it names
the paths and lets the steer carry both dispositions.

What it must never do is fire on open work. A dirty tree mid-task is
normal, and gating it would recreate the over-firing GH-1339 removed.
"""

from __future__ import annotations

from pathlib import Path

from dev10x.hooks.stop_verdict import StopSignal, TaskSignal, auto_advances, decide

from .conftest import DEPLETED_PLAN, PENDING_PLAN
from .test_stop_verdict import _assistant, _text
from .test_stop_verdict import _transcript as _write_transcript

_DIRTY = ("src/dev10x/hooks/stop_verdict.py", "tests/hooks/test_stop_verdict.py")


def _transcript(*, tmp_path: Path, closing: str = "All done.") -> str:
    return _write_transcript(
        tmp_path=tmp_path,
        entries=[
            {"type": "user", "message": {"role": "user", "content": "carry on"}},
            _assistant(blocks=[_text(text=closing)]),
        ],
    )


class TestADirtyTreeMeansNotDone:
    def test_a_depleted_list_with_changes_blocks(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        verdict = decide(
            data={"session_id": "d1", "transcript_path": _transcript(tmp_path=tmp_path)},
            plan=DEPLETED_PLAN,
            dirty=_DIRTY,
        )

        assert verdict.block is True
        assert verdict.signal == StopSignal.DIRTY_TREE

    def test_the_steer_names_every_changed_path(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        """A path the agent cannot see is one it cannot act on."""
        verdict = decide(
            data={"session_id": "d2", "transcript_path": _transcript(tmp_path=tmp_path)},
            plan=DEPLETED_PLAN,
            dirty=_DIRTY,
        )

        for path in _DIRTY:
            assert path in verdict.reason

    def test_the_steer_routes_to_the_commit_skill(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        """An unfinished commit is an instruction, not a question."""
        verdict = decide(
            data={"session_id": "d3", "transcript_path": _transcript(tmp_path=tmp_path)},
            plan=DEPLETED_PLAN,
            dirty=_DIRTY,
        )

        assert "Dev10x:git-commit" in verdict.reason
        assert "AskUserQuestion" not in verdict.reason

    def test_the_steer_carries_the_shared_worktree_escape(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        """Nothing here can tell whose changes these are — so say so.

        A session and its subagents share one worktree. Telling an agent
        to commit files it never touched would be worse than the missing
        commit this catches.
        """
        verdict = decide(
            data={"session_id": "d4", "transcript_path": _transcript(tmp_path=tmp_path)},
            plan=DEPLETED_PLAN,
            dirty=_DIRTY,
        )
        reason = verdict.reason.replace("\n", " ")

        assert "did not touch" in reason
        assert "another session" in reason


class TestOpenWorkIsNeverGatedOnTheTree:
    def test_open_work_continues_without_mentioning_the_tree(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        """WIP mid-task is normal, so the tree is not consulted yet.

        The turn still continues (GH-1366), but on the plan's authority
        — the steer names the next task, not the uncommitted files.
        """
        verdict = decide(
            data={"session_id": "d5", "transcript_path": _transcript(tmp_path=tmp_path)},
            plan=PENDING_PLAN,
            dirty=_DIRTY,
        )

        assert verdict.signal == StopSignal.CONTINUE
        assert "Monitor CI" in verdict.reason
        assert "stop_verdict.py" not in verdict.reason

    def test_an_absent_list_advances_with_a_dirty_tree(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        """A model without task tools must not be gated on the tree either."""
        verdict = decide(
            data={"session_id": "d6", "transcript_path": _transcript(tmp_path=tmp_path)},
            plan=None,
            dirty=_DIRTY,
        )

        assert verdict.block is False
        assert verdict.signal == StopSignal.NO_TASK_LIST


class TestACleanTreeIsUnchanged:
    def test_a_depleted_list_with_a_clean_tree_asks_to_stand_down(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        verdict = decide(
            data={"session_id": "d7", "transcript_path": _transcript(tmp_path=tmp_path)},
            plan=DEPLETED_PLAN,
            dirty=(),
        )

        assert verdict.block is True
        assert verdict.signal == StopSignal.BLOCKED
        assert "stand down" in verdict.reason.lower()

    def test_an_unreadable_tree_reads_as_clean(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        """Every degradation in this module points toward letting the turn end.

        A git read that failed is not evidence of uncommitted work, and
        inventing a block from it would be the one failure mode the
        module refuses everywhere else.
        """
        verdict = decide(
            data={"session_id": "d8", "transcript_path": _transcript(tmp_path=tmp_path)},
            plan=DEPLETED_PLAN,
            dirty=None,
        )

        assert verdict.signal == StopSignal.BLOCKED


class TestTheRuleIsAPureFunction:
    def test_the_rule_never_sees_the_tree(self) -> None:
        """`auto_advances` decides from the plan alone.

        The tree is consulted only after it has said the work is done,
        which is what keeps WIP mid-task out of the gate entirely.
        """
        assert auto_advances(signal=TaskSignal(has_task_list=True)) is False
        assert (
            auto_advances(signal=TaskSignal(open_subjects=("Monitor CI",), has_task_list=True))
            is True
        )


class TestTheSignalIsLegible:
    def test_dirty_tree_reprs_as_a_member(self) -> None:
        assert repr(StopSignal.DIRTY_TREE) == "StopSignal.DIRTY_TREE"
