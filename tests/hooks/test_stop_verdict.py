"""Tests for the Stop verdict decision logic (GH-1251)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from dev10x.hooks.session_dispatch import build_stop_verdict
from dev10x.hooks.stop_verdict import (
    StopSignal,
    StopVerdict,
    _marker_path,
    _read_turn,
    asked_a_question,
    blocked_recently,
    decide,
    final_text,
    record_block,
    task_signal,
)

from .conftest import DEPLETED_PLAN, PENDING_PLAN


def _assistant(*, blocks: list[dict]) -> dict:
    return {"type": "assistant", "message": {"role": "assistant", "content": blocks}}


def _text(*, text: str) -> dict:
    return {"type": "text", "text": text}


def _ask() -> dict:
    return {"type": "tool_use", "name": "AskUserQuestion", "input": {}}


def _transcript(*, tmp_path: Path, entries: list[dict]) -> str:
    path = tmp_path / "transcript.jsonl"
    path.write_text("\n".join(json.dumps(entry) for entry in entries), encoding="utf-8")
    return str(path)


class TestBlocksATurnEndingOnADecision:
    """GH-1339 narrowed this to a single state: a depleted task list.

    Every case here therefore supplies a list that exists and holds
    nothing open. Neither a bare "this turn used no widget" nor a prose
    deferral blocks any more — the sibling
    ``test_stop_verdict_open_work`` module pins both.
    """

    def test_blocks_when_the_work_is_done(
        self,
        tmp_path: Path,
        isolated_markers: Path,
    ) -> None:
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=[
                {"type": "user", "message": {"role": "user", "content": "go"}},
                _assistant(blocks=[_text(text="All done.")]),
            ],
        )

        verdict = decide(
            data={"session_id": "s1", "transcript_path": transcript},
            plan=DEPLETED_PLAN,
        )

        assert verdict.block is True
        assert "Dev10x:ask" in verdict.reason

    def test_a_done_session_still_ends_on_a_widget(
        self,
        tmp_path: Path,
        isolated_markers: Path,
    ) -> None:
        """Nothing open is not a licence to close on prose."""
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=[
                {"type": "user", "message": {"role": "user", "content": "finish"}},
                _assistant(blocks=[_text(text="Everything is merged.")]),
            ],
        )

        verdict = decide(
            data={"session_id": "s3", "transcript_path": transcript},
            plan=DEPLETED_PLAN,
        )

        assert verdict.block is True
        assert "stand down" in verdict.reason

    def test_the_steer_carries_a_recommendation(
        self,
        tmp_path: Path,
        isolated_markers: Path,
    ) -> None:
        """Pre-collapse `guided` blocked WITH a recommendation, never open-endedly."""
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=[
                {"type": "user", "message": {"role": "user", "content": "carry on"}},
                _assistant(blocks=[_text(text="Committed.")]),
            ],
        )

        verdict = decide(
            data={"session_id": "s4", "transcript_path": transcript},
            plan=DEPLETED_PLAN,
        )

        assert verdict.block is True
        assert "(Recommended)" in verdict.reason


class TestLetsATurnEnd:
    def test_a_turn_that_asked_is_not_blocked(
        self,
        tmp_path: Path,
        isolated_markers: Path,
    ) -> None:
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=[
                {"type": "user", "message": {"role": "user", "content": "go"}},
                _assistant(blocks=[_text(text="Which one?"), _ask()]),
            ],
        )

        verdict = decide(
            data={"session_id": "s6", "transcript_path": transcript},
            plan=None,
        )

        assert verdict.block is False

    def test_stop_hook_active_short_circuits(
        self,
        tmp_path: Path,
        isolated_markers: Path,
    ) -> None:
        """The harness loop guard — a continuation must be allowed to end."""
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=[
                {"type": "user", "message": {"role": "user", "content": "go"}},
                _assistant(blocks=[_text(text="Done.")]),
            ],
        )

        verdict = decide(
            data={
                "session_id": "s7",
                "transcript_path": transcript,
                "stop_hook_active": True,
            },
            plan=None,
        )

        assert verdict.block is False

    def test_a_recorded_block_suppresses_the_next_one(
        self,
        tmp_path: Path,
        isolated_markers: Path,
    ) -> None:
        """Belt and braces — holds even if stop_hook_active never arrives.

        ``decide`` is pure: it READS the marker, and the wiring in
        ``build_stop_verdict`` writes it (see
        ``TestWiringRecordsTheBlock``).
        """
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=[
                {"type": "user", "message": {"role": "user", "content": "go"}},
                _assistant(blocks=[_text(text="Done.")]),
            ],
        )
        data = {"session_id": "s8", "transcript_path": transcript}

        first = decide(data=data, plan=DEPLETED_PLAN)
        record_block(session_id="s8")
        second = decide(data=data, plan=DEPLETED_PLAN)

        assert first.block is True
        assert second.block is False

    def test_an_unreadable_transcript_is_no_evidence(
        self,
        isolated_markers: Path,
    ) -> None:
        verdict = decide(
            data={"session_id": "s9", "transcript_path": "/nonexistent/transcript.jsonl"},
            plan=None,
        )

        assert verdict.block is False

    def test_a_missing_transcript_path_is_no_evidence(
        self,
        isolated_markers: Path,
    ) -> None:
        assert decide(data={"session_id": "s10"}, plan=None).block is False

    def test_a_corrupt_transcript_is_no_evidence(
        self,
        tmp_path: Path,
        isolated_markers: Path,
    ) -> None:
        """UnicodeDecodeError is a ValueError, so OSError alone misses it."""
        path = tmp_path / "binary.jsonl"
        path.write_bytes(b"\xff\xfe\x00\x01 not utf-8")

        verdict = decide(data={"session_id": "s13", "transcript_path": str(path)}, plan=None)

        assert verdict.block is False

    def test_a_turn_with_no_assistant_output_is_no_evidence(
        self,
        tmp_path: Path,
        isolated_markers: Path,
    ) -> None:
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=[{"type": "user", "message": {"role": "user", "content": "go"}}],
        )

        assert (
            decide(data={"session_id": "s11", "transcript_path": transcript}, plan=None).block
            is False
        )


class TestTranscriptReading:
    def test_only_the_current_turn_counts(self, tmp_path: Path) -> None:
        """An AskUserQuestion the supervisor already answered does not cover this turn.

        Reading stops at the last human message, so the earlier ask is
        never even parsed.
        """
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=[
                {"type": "user", "message": {"role": "user", "content": "a"}},
                _assistant(blocks=[_ask()]),
                {"type": "user", "message": {"role": "user", "content": "b"}},
                _assistant(blocks=[_text(text="Done.")]),
            ],
        )

        turn = _read_turn(transcript_path=transcript)

        assert asked_a_question(entries=turn) is False
        assert len(turn) == 1

    def test_the_turn_is_returned_oldest_first(self, tmp_path: Path) -> None:
        """Reading backwards must not reverse the turn it hands back."""
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=[
                {"type": "user", "message": {"role": "user", "content": "go"}},
                _assistant(blocks=[_text(text="first")]),
                _assistant(blocks=[_text(text="second")]),
            ],
        )

        turn = _read_turn(transcript_path=transcript)

        assert final_text(entries=turn) == "second"

    def test_a_transcript_with_no_user_message_is_all_entries(self, tmp_path: Path) -> None:
        transcript = _transcript(
            tmp_path=tmp_path, entries=[_assistant(blocks=[_text(text="hi")])]
        )

        assert len(_read_turn(transcript_path=transcript)) == 1

    def test_malformed_lines_are_skipped(self, tmp_path: Path, isolated_markers: Path) -> None:
        path = tmp_path / "transcript.jsonl"
        path.write_text(
            "\n".join(
                [
                    json.dumps({"type": "user", "message": {"role": "user", "content": "go"}}),
                    # All inside the current turn — reading stops at the
                    # user message above, so anything before it is never
                    # parsed and could not exercise these guards.
                    "{not json",
                    "",
                    json.dumps(_assistant(blocks=[_text(text="Done.")])),
                    "[1, 2, 3]",
                ]
            ),
            encoding="utf-8",
        )

        verdict = decide(
            data={"session_id": "s12", "transcript_path": str(path)}, plan=DEPLETED_PLAN
        )

        assert verdict.block is True

    def test_final_text_takes_the_last_prose_block(self) -> None:
        entries = [
            _assistant(blocks=[_text(text="first")]),
            _assistant(blocks=[_ask()]),
            _assistant(blocks=[_text(text="last")]),
        ]

        assert final_text(entries=entries) == "last"

    def test_final_text_is_empty_without_prose(self) -> None:
        assert final_text(entries=[_assistant(blocks=[_ask()])]) == ""

    def test_top_level_content_is_read_too(self) -> None:
        """Some transcript shapes put content outside a `message` wrapper."""
        entries = [{"type": "assistant", "content": [_text(text="plain")]}]

        assert final_text(entries=entries) == "plain"

    def test_non_list_content_contributes_nothing(self) -> None:
        entries = [{"type": "assistant", "message": {"content": "a string"}}]

        assert final_text(entries=entries) == ""


class TestTaskSignal:
    def test_no_plan_yields_no_signal(self) -> None:
        signal = task_signal(plan=None)

        assert signal.has_open_work is False
        assert signal.has_task_list is False

    def test_a_plan_without_tasks_yields_no_signal(self) -> None:
        assert task_signal(plan={"context": {}}).has_open_work is False

    def test_in_progress_counts_as_open(self) -> None:
        signal = task_signal(plan={"tasks": [{"subject": "Verify", "status": "in_progress"}]})

        assert signal.open_subjects == ("Verify",)

    def test_blank_subjects_are_dropped(self) -> None:
        signal = task_signal(plan={"tasks": [{"subject": "   ", "status": "pending"}]})

        assert signal.has_open_work is False

    def test_completed_phases_read_as_a_depleted_list(self) -> None:
        """GH-1339 retired the phase-boundary detector; depletion replaced it."""
        signal = task_signal(
            plan={
                "tasks": [
                    {"subject": "Phase 1: a", "status": "completed"},
                    {"subject": "Phase 2: b", "status": "completed"},
                ]
            }
        )

        assert signal.is_depleted is True


class TestEnvelope:
    def test_a_blocking_verdict_renders_the_decision_payload(self) -> None:
        envelope = StopVerdict(block=True, reason="steer text").to_envelope()

        assert envelope == {"decision": "block", "reason": "steer text"}


class TestMarker:
    def test_the_real_marker_path_is_session_scoped(self) -> None:
        """Asserted unpatched — every other test replaces this builder."""
        path = _marker_path(session_id="abc")

        assert path.name == "abc.marker"
        assert path.parent == Path("/tmp/Dev10x/stop-verdict")

    def test_a_session_without_an_id_still_has_a_marker(self) -> None:
        assert _marker_path(session_id="").name == "unknown.marker"

    def test_a_fresh_session_was_not_blocked_recently(self, isolated_markers: Path) -> None:
        assert blocked_recently(session_id="fresh") is False

    def test_a_recorded_block_is_seen(self, isolated_markers: Path) -> None:
        record_block(session_id="seen")

        assert blocked_recently(session_id="seen") is True

    def test_the_cooldown_expires(self, isolated_markers: Path) -> None:
        record_block(session_id="old")

        assert blocked_recently(session_id="old", now=1e12) is False

    def test_recording_is_best_effort_when_unwritable(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A marker that cannot be written must not become a second block.

        It must also not be silent: an unwritable marker directory
        disables the cooldown guard, and the symptom is a hook that
        re-blocks every turn with nothing naming the cause.
        """
        blocker = tmp_path / "afile"
        blocker.write_text("x", encoding="utf-8")
        monkeypatch.setattr(
            "dev10x.hooks.stop_verdict._marker_path",
            lambda *, session_id: blocker / "nested" / "m.marker",
        )

        record_block(session_id="unwritable")

        assert blocked_recently(session_id="unwritable") is False
        assert "writing the cooldown marker" in capsys.readouterr().err

    def test_an_unreadable_marker_is_diagnosed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A real OSError is not the same as "no marker yet"."""
        blocker = tmp_path / "afile"
        blocker.write_text("x", encoding="utf-8")
        monkeypatch.setattr(
            "dev10x.hooks.stop_verdict._marker_path",
            lambda *, session_id: blocker / "nested" / "m.marker",
        )

        assert blocked_recently(session_id="unreadable") is False
        assert "reading the cooldown marker" in capsys.readouterr().err

    def test_a_missing_marker_is_silent(
        self,
        isolated_markers: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The first block of a session is the expected case, not a fault."""
        assert blocked_recently(session_id="first") is False
        assert capsys.readouterr().err == ""


class TestSignalIsReported:
    """GH-1257: which branch let the turn end has to be observable.

    Retiring the cooldown marker is safe only with positive evidence
    that ``stop_hook_active`` arrives set on a continuation — and the
    audit log carried nothing but wrap-phase timing, so the question
    could not be answered from the field at all.
    """

    def test_stop_hook_active_is_named(self, tmp_path: Path, isolated_markers: Path) -> None:
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=[
                {"type": "user", "message": {"role": "user", "content": "go"}},
                _assistant(blocks=[_text(text="Done.")]),
            ],
        )

        verdict = decide(
            data={
                "session_id": "sig1",
                "transcript_path": transcript,
                "stop_hook_active": True,
            },
            plan=None,
        )

        assert verdict.signal == StopSignal.STOP_HOOK_ACTIVE

    def test_the_cooldown_branch_is_distinguishable_from_it(
        self,
        tmp_path: Path,
        isolated_markers: Path,
    ) -> None:
        # The whole point: the two guards must not report the same
        # thing, or the evidence cannot separate them.
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=[
                {"type": "user", "message": {"role": "user", "content": "go"}},
                _assistant(blocks=[_text(text="Done.")]),
            ],
        )
        data = {"session_id": "sig2", "transcript_path": transcript}

        blocked = decide(data=data, plan=DEPLETED_PLAN)
        record_block(session_id="sig2")
        suppressed = decide(data=data, plan=DEPLETED_PLAN)

        assert blocked.signal == StopSignal.BLOCKED
        assert suppressed.signal == StopSignal.COOLDOWN

    def test_an_asking_turn_is_named(self, tmp_path: Path, isolated_markers: Path) -> None:
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=[
                {"type": "user", "message": {"role": "user", "content": "go"}},
                _assistant(blocks=[_ask()]),
            ],
        )

        verdict = decide(data={"session_id": "sig3", "transcript_path": transcript}, plan=None)

        assert verdict.signal == StopSignal.ASKED

    def test_an_unreadable_transcript_is_named(self, isolated_markers: Path) -> None:
        verdict = decide(data={"session_id": "sig4", "transcript_path": ""}, plan=None)

        assert verdict.signal == StopSignal.NO_TRANSCRIPT

    def test_the_wiring_attributes_the_signal_to_the_audit_record(
        self,
        tmp_path: Path,
        isolated_markers: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Without this the signal exists but never reaches the log, which
        # is the state GH-1257 is stuck in.
        monkeypatch.setattr("dev10x.hooks.session_dispatch._get_toplevel", lambda: None)
        recorded: dict[str, str] = {}
        monkeypatch.setattr(
            "dev10x.hooks.session_dispatch.set_decision_attribution",
            lambda *, rule_id, reason: recorded.update(rule_id=rule_id, reason=reason),
        )
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=[
                {"type": "user", "message": {"role": "user", "content": "go"}},
                _assistant(blocks=[_text(text="Done.")]),
            ],
        )

        build_stop_verdict(
            data={
                "session_id": "sig5",
                "transcript_path": transcript,
                "stop_hook_active": True,
            }
        )

        assert recorded == {"rule_id": "stop-verdict", "reason": StopSignal.STOP_HOOK_ACTIVE}


class TestWiringRecordsTheBlock:
    """``build_stop_verdict`` is the layer that turns a verdict into state."""

    @pytest.fixture()
    def no_plan(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "dev10x.hooks.session_dispatch._get_toplevel",
            lambda: None,
        )

    @pytest.fixture()
    def depleted_plan(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A plan whose tasks are all complete — the blocking state.

        Wiring tests need a turn that actually blocks, and since GH-1339
        an absent plan no longer is one.
        """
        monkeypatch.setattr(
            "dev10x.hooks.session_dispatch._get_toplevel",
            lambda: "/repo",
        )
        monkeypatch.setattr(
            "dev10x.hooks.session_dispatch.read_plan_summary",
            lambda *, toplevel: {"plan": {"status": "in_progress"}, **DEPLETED_PLAN},
        )

    def test_a_block_is_returned_and_recorded_once(
        self,
        tmp_path: Path,
        isolated_markers: Path,
        depleted_plan: None,
    ) -> None:
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=[
                {"type": "user", "message": {"role": "user", "content": "go"}},
                _assistant(blocks=[_text(text="Done.")]),
            ],
        )
        data = {"session_id": "w1", "transcript_path": transcript}

        first = build_stop_verdict(data=data)
        second = build_stop_verdict(data=data)

        assert first is not None
        assert first.block is True
        assert second is None

    def test_a_turn_that_asked_returns_none(
        self,
        tmp_path: Path,
        isolated_markers: Path,
        no_plan: None,
    ) -> None:
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=[
                {"type": "user", "message": {"role": "user", "content": "go"}},
                _assistant(blocks=[_ask()]),
            ],
        )

        assert build_stop_verdict(data={"session_id": "w2", "transcript_path": transcript}) is None

    def test_the_payload_is_read_from_stdin_when_absent(
        self,
        tmp_path: Path,
        isolated_markers: Path,
        depleted_plan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The feature is also callable as a bare hook entry point."""
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=[
                {"type": "user", "message": {"role": "user", "content": "go"}},
                _assistant(blocks=[_text(text="Done.")]),
            ],
        )
        monkeypatch.setattr(
            "sys.stdin",
            io.StringIO(json.dumps({"session_id": "w4", "transcript_path": transcript})),
        )

        verdict = build_stop_verdict()

        assert verdict is not None
        assert verdict.block is True

    def test_malformed_stdin_lets_the_turn_end(
        self,
        isolated_markers: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO("{not json"))

        assert build_stop_verdict() is None

    def test_the_plan_decides_the_verdict(
        self,
        tmp_path: Path,
        isolated_markers: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The wiring's whole job: find the plan and hand it to the rule.

        Asserted through the verdict rather than the steer text, since
        GH-1339 left one blocking state whose message names no task.
        """
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=[
                {"type": "user", "message": {"role": "user", "content": "go"}},
                _assistant(blocks=[_text(text="Committed.")]),
            ],
        )
        monkeypatch.setattr(
            "dev10x.hooks.session_dispatch._get_toplevel",
            lambda: "/repo",
        )
        # The real `Plan.to_dict` shape: tasks sit beside the metadata,
        # not inside it. Reaching for summary["plan"] was the GH-1339
        # bug that blanked the signal in the field.
        monkeypatch.setattr(
            "dev10x.hooks.session_dispatch.read_plan_summary",
            lambda *, toplevel: {"plan": {"status": "in_progress"}, **PENDING_PLAN},
        )

        assert build_stop_verdict(data={"session_id": "w3", "transcript_path": transcript}) is None

        monkeypatch.setattr(
            "dev10x.hooks.session_dispatch.read_plan_summary",
            lambda *, toplevel: {"plan": {"status": "in_progress"}, **DEPLETED_PLAN},
        )

        verdict = build_stop_verdict(data={"session_id": "w5", "transcript_path": transcript})

        assert verdict is not None
        assert verdict.block is True
