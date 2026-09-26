"""GH-1314: the Stop gate has two audiences it must not address.

"A turn always ends on a widget" presumes a supervisor on the other end.
``decide`` had four exit branches before its block and none of them asked
who was listening, so two cases fell through:

  - a **subagent**, which has no supervisor at all. One was observed
    ending its report with "No open decisions on my end. Are we done
    here?" — a near-verbatim echo of this module's own no-open-work
    steer. It was not inventing a status check; it was complying with a
    block it should never have received.
  - a session the supervisor **parked**. The widget's only answers
    re-armed it next turn, so there was no way to say "stop asking until
    I speak".

Both branches are non-blocking and both carry their own ``StopSignal``,
so the guard is observable in the field rather than assumed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.hooks.stop_verdict import (
    StopSignal,
    _standby_path,
    decide,
    is_subagent,
    standby_holds,
)

from .conftest import DEPLETED_PLAN

_STANDBY_ANSWER = (
    'Your questions have been answered: "Anything open?"="On standby — not waiting on you".'
)


def _user(*, uuid: str = "u1", content: object = "go") -> dict:
    return {"type": "user", "uuid": uuid, "message": {"role": "user", "content": content}}


def _answered(*, uuid: str = "u1", text: str = _STANDBY_ANSWER) -> dict:
    """A user entry carrying a widget answer, the shape the harness writes."""
    return _user(
        uuid=uuid,
        content=[{"type": "tool_result", "content": [{"type": "text", "text": text}]}],
    )


def _closing(*, text: str = "All four are committed.") -> dict:
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


def _transcript(*, tmp_path: Path, entries: list[dict], name: str = "transcript") -> str:
    """Write one turn to its own JSONL file.

    ``name`` distinguishes successive turns within a test — the marker
    is keyed to the boundary message, not to the transcript path, so the
    two must be able to differ independently.
    """
    path = tmp_path / f"{name}.jsonl"
    path.write_text("\n".join(json.dumps(entry) for entry in entries), encoding="utf-8")
    return str(path)


class TestASubagentIsNeverBlocked:
    def test_the_documented_event_name_is_enough(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        transcript = _transcript(tmp_path=tmp_path, entries=[_user(), _closing()])

        verdict = decide(
            data={
                "session_id": "sub1",
                "transcript_path": transcript,
                "hook_event_name": "SubagentStop",
            },
            plan=None,
        )

        assert verdict.block is False
        assert verdict.signal == StopSignal.SUBAGENT

    @pytest.mark.parametrize(
        "field",
        ["is_subagent", "subagent", "subagent_id", "agent_id", "parent_session_id"],
    )
    def test_a_retired_guess_no_longer_counts(self, field: str) -> None:
        """GH-1347: none of these ever arrived in 712 audit records.

        A key re-enters only from a captured payload, so the guesses must
        not quietly come back as coverage.
        """
        assert is_subagent(data={field: "a7634aca"}) is False

    def test_an_ordinary_payload_is_not_a_subagent(self) -> None:
        """Absence degrades toward the pre-GH-1314 behaviour, not past it."""
        assert is_subagent(data={"session_id": "s", "hook_event_name": "Stop"}) is False

    def test_the_transcript_path_names_a_subagent(self) -> None:
        """GH-1340: the discriminator that actually arrives.

        None of the payload keys above has ever been seen in the field —
        ``StopSignal.SUBAGENT`` fired 0 times in 224 audit records. The
        transcript layout does distinguish them, and ``decide`` already
        reads that path. Shape captured from a live dispatch.
        """
        path = (
            "/home/janusz/.claude/projects/-work-dx--worktrees-Dev10x-Claude-5/"
            "0423993e-9493-4920-9c23-b61df77fe6d3/subagents/agent-a0932d5778dc9cc06.jsonl"
        )

        assert is_subagent(data={"transcript_path": path}) is True

    def test_a_main_session_transcript_path_does_not(self) -> None:
        """The sibling file, one directory up — captured from the same session."""
        path = (
            "/home/janusz/.claude/projects/-work-dx--worktrees-Dev10x-Claude-5/"
            "0423993e-9493-4920-9c23-b61df77fe6d3.jsonl"
        )

        assert is_subagent(data={"transcript_path": path}) is False

    def test_a_subagent_transcript_ends_the_turn(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        """The branch becomes reachable, which is the whole point of GH-1340.

        The signal is ``SUBAGENT_PATH`` rather than ``SUBAGENT`` so the
        audit log can show which discriminator carried it — the evidence
        needed before the never-firing payload keys can be retired.
        """
        nested = tmp_path / "subagents"
        nested.mkdir()
        transcript = _transcript(
            tmp_path=nested, entries=[_user(), _closing()], name="agent-a0932d5778dc9cc06"
        )

        verdict = decide(
            data={"session_id": "sub2", "transcript_path": transcript},
            plan=DEPLETED_PLAN,
        )

        assert verdict.block is False
        assert verdict.signal == StopSignal.SUBAGENT_PATH

    def test_the_main_session_is_still_blocked(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        """The unchanged half of the contract.

        The plan is a *depleted* one rather than absent since GH-1339: an
        absent list is no longer evidence the work is finished, so it no
        longer reaches the block this test is about.
        """
        transcript = _transcript(tmp_path=tmp_path, entries=[_user(), _closing()])

        verdict = decide(
            data={"session_id": "main1", "transcript_path": transcript},
            plan=DEPLETED_PLAN,
        )

        assert verdict.block is True
        assert verdict.signal == StopSignal.BLOCKED


class TestStandbyParksTheGate:
    def test_choosing_standby_ends_the_turn(self, tmp_path: Path, isolated_markers: Path) -> None:
        transcript = _transcript(tmp_path=tmp_path, entries=[_answered(), _closing()])

        verdict = decide(
            data={"session_id": "park1", "transcript_path": transcript},
            plan=None,
        )

        assert verdict.block is False
        assert verdict.signal == StopSignal.STANDBY

    def test_it_holds_on_a_later_turn_with_no_new_message(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        """A background wake-up is not the supervisor speaking."""
        standby = _transcript(tmp_path=tmp_path, entries=[_answered(), _closing()])
        decide(data={"session_id": "park2", "transcript_path": standby}, plan=None)

        later = _transcript(
            tmp_path=tmp_path,
            name="later",
            entries=[_answered(text="irrelevant"), _closing(text="Still nothing new.")],
        )
        verdict = decide(data={"session_id": "park2", "transcript_path": later}, plan=None)

        assert verdict.signal == StopSignal.STANDBY

    def test_the_supervisor_speaking_clears_it(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        """Standby is a pause, not a disable — this is the whole difference."""
        standby = _transcript(tmp_path=tmp_path, entries=[_answered(uuid="u1"), _closing()])
        decide(data={"session_id": "park3", "transcript_path": standby}, plan=None)

        spoke = _transcript(
            tmp_path=tmp_path,
            name="spoke",
            entries=[_user(uuid="u2", content="actually, one more thing"), _closing()],
        )
        verdict = decide(
            data={"session_id": "park3", "transcript_path": spoke}, plan=DEPLETED_PLAN
        )

        assert verdict.block is True
        assert verdict.signal == StopSignal.BLOCKED

    def test_the_marker_is_dropped_once_stale(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        standby = _transcript(tmp_path=tmp_path, entries=[_answered(uuid="u1"), _closing()])
        decide(data={"session_id": "park4", "transcript_path": standby}, plan=None)
        marker = isolated_markers / "park4.standby"
        assert marker.exists()

        spoke = _transcript(
            tmp_path=tmp_path,
            name="spoke",
            entries=[_user(uuid="u2"), _closing()],
        )
        decide(data={"session_id": "park4", "transcript_path": spoke}, plan=None)

        assert not marker.exists()

    def test_a_plain_answer_does_not_park(self, tmp_path: Path, isolated_markers: Path) -> None:
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=[_answered(text='"Anything open?"="Yes, keep going".'), _closing()],
        )

        verdict = decide(
            data={"session_id": "park5", "transcript_path": transcript}, plan=DEPLETED_PLAN
        )

        assert verdict.block is True

    def test_a_string_tool_result_is_read_too(self, isolated_markers: Path) -> None:
        """The harness writes tool_result content as a string or a block list."""
        boundary = {
            "type": "user",
            "uuid": "u9",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "content": _STANDBY_ANSWER}],
            },
        }

        assert standby_holds(session_id="park6", entries=[boundary], boundary=None) is True

    def test_no_boundary_message_is_not_standby(self, isolated_markers: Path) -> None:
        assert standby_holds(session_id="park7", entries=[], boundary=None) is False

    def test_an_answer_the_supervisor_typed_over_is_still_read(
        self, isolated_markers: Path
    ) -> None:
        """A boundary entry can carry a widget answer alongside prose.

        Typing while a tool returns keeps that entry the boundary
        (GH-1334), so the answer has to be read there as well as in the
        turn — otherwise it is dropped on the one entry carrying it.
        """
        boundary = {
            "type": "user",
            "uuid": "u1",
            "message": {
                "role": "user",
                "content": [
                    {"type": "tool_result", "content": _STANDBY_ANSWER},
                    {"type": "text", "text": "and take the evening off"},
                ],
            },
        }

        assert standby_holds(session_id="park8", entries=[], boundary=boundary) is True


class TestStandbyDegradesQuietly:
    """The marker must never be the reason a turn cannot end.

    Every degradation in this module points toward letting the turn
    finish; these are the standby marker's share of that, mirroring
    what the cooldown marker already guarantees.
    """

    def test_a_corrupt_marker_reads_as_no_standby(
        self, isolated_markers: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        isolated_markers.mkdir(parents=True, exist_ok=True)
        (isolated_markers / "bad.standby").write_text("{not json", encoding="utf-8")

        assert standby_holds(session_id="bad", entries=[], boundary=_user(uuid="u1")) is False
        assert "standby marker" in capsys.readouterr().err

    def test_recording_is_best_effort_when_unwritable(
        self,
        isolated_markers: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A marker that cannot be written still parks this turn."""

        def refuse(*args: object, **kwargs: object) -> None:
            raise OSError("read-only file system")

        monkeypatch.setattr("dev10x.hooks.stop_verdict.atomic_write_text", refuse)

        assert standby_holds(session_id="ro", entries=[_answered()], boundary=None) is True
        assert "writing the standby marker" in capsys.readouterr().err

    def test_a_non_tool_result_block_contributes_nothing(self, isolated_markers: Path) -> None:
        """Prose in the boundary message is not an answer to the widget."""
        boundary = {
            "type": "user",
            "uuid": "u1",
            "message": {
                "role": "user",
                "content": [
                    {"type": "text", "text": "on standby"},
                    {"type": "tool_result", "content": "keep going"},
                ],
            },
        }

        assert standby_holds(session_id="prose", entries=[], boundary=boundary) is False


class TestTheRealStandbyPath:
    def test_it_is_session_scoped(self) -> None:
        """Unpatched, so the shared fixture cannot hide a wrong path.

        Standby has to be per-session: one parked session must not
        silence the gate in another running beside it.
        """
        first = _standby_path(session_id="alpha")
        second = _standby_path(session_id="beta")

        assert first != second
        assert first.name == "alpha.standby"
        assert first.parent == second.parent

    def test_a_session_without_an_id_still_has_a_path(self) -> None:
        assert _standby_path(session_id="").name == "unknown.standby"


class TestSignalsAreLegible:
    def test_the_new_signals_repr_as_members(self) -> None:
        """The audit record is read by people; a bare value is not a branch name."""
        assert repr(StopSignal.SUBAGENT) == "StopSignal.SUBAGENT"
        assert repr(StopSignal.SUBAGENT_PATH) == "StopSignal.SUBAGENT_PATH"
        assert repr(StopSignal.STANDBY) == "StopSignal.STANDBY"


class TestTheSteerOffersTheOption:
    def test_a_blocking_reason_names_standby(self, tmp_path: Path, isolated_markers: Path) -> None:
        """A terminal answer nobody is told about is one nobody can pick."""
        transcript = _transcript(tmp_path=tmp_path, entries=[_user(), _closing()])

        verdict = decide(
            data={"session_id": "steer1", "transcript_path": transcript}, plan=DEPLETED_PLAN
        )

        assert "On standby" in verdict.reason
        assert "not a permanent disable" in verdict.reason
