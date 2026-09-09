"""Tests for the Stop verdict decision logic (GH-1251)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from dev10x.hooks.session_dispatch import build_stop_verdict
from dev10x.hooks.stop_verdict import (
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


@pytest.fixture()
def isolated_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the once-per-turn marker at a temp dir, not the real /tmp."""
    marker_dir = tmp_path / "markers"
    monkeypatch.setattr(
        "dev10x.hooks.stop_verdict._marker_path",
        lambda *, session_id: marker_dir / f"{session_id or 'unknown'}.marker",
    )
    return marker_dir


class TestBlocksATurnWithNoWidget:
    def test_blocks_when_the_turn_never_asked(
        self,
        tmp_path: Path,
        isolated_marker: Path,
    ) -> None:
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=[
                {"type": "user", "message": {"role": "user", "content": "go"}},
                _assistant(blocks=[_text(text="All done. Want me to file that?")]),
            ],
        )

        verdict = decide(
            data={"session_id": "s1", "transcript_path": transcript},
            plan=None,
        )

        assert verdict.block is True
        assert "Dev10x:ask" in verdict.reason

    def test_blocks_an_imperative_deferral_with_no_question_mark(
        self,
        tmp_path: Path,
        isolated_marker: Path,
    ) -> None:
        """GH-1251 instance 3 — the "?" test alone would miss this."""
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=[
                {"type": "user", "message": {"role": "user", "content": "plan it"}},
                _assistant(blocks=[_text(text="say go and I'll run 4.1 through 4.11.")]),
            ],
        )

        verdict = decide(
            data={"session_id": "s2", "transcript_path": transcript},
            plan=None,
        )

        assert verdict.block is True
        assert "instance 3" in verdict.reason

    def test_a_done_session_still_ends_on_a_widget(
        self,
        tmp_path: Path,
        isolated_marker: Path,
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
            plan={"tasks": [{"subject": "Ship it", "status": "completed"}]},
        )

        assert verdict.block is True
        assert "No open loops. Are we done?" in verdict.reason

    def test_open_work_names_the_next_loop(
        self,
        tmp_path: Path,
        isolated_marker: Path,
    ) -> None:
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=[
                {"type": "user", "message": {"role": "user", "content": "carry on"}},
                _assistant(blocks=[_text(text="Committed.")]),
            ],
        )

        verdict = decide(
            data={"session_id": "s4", "transcript_path": transcript},
            plan={"tasks": [{"subject": "Monitor CI", "status": "pending"}]},
        )

        assert verdict.block is True
        assert "Monitor CI" in verdict.reason

    def test_a_phase_boundary_names_the_skipped_gate(
        self,
        tmp_path: Path,
        isolated_marker: Path,
    ) -> None:
        """The structural detector the GH-1251 comment recommends as primary."""
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=[
                {"type": "user", "message": {"role": "user", "content": "plan"}},
                _assistant(blocks=[_text(text="Here is the plan.")]),
            ],
        )

        verdict = decide(
            data={"session_id": "s5", "transcript_path": transcript},
            plan={
                "tasks": [
                    {"subject": "Phase 3: Build work plan", "status": "completed"},
                    {"subject": "Phase 4: Execute plan", "status": "pending"},
                ]
            },
        )

        assert verdict.block is True
        assert "plan gate" in verdict.reason


class TestLetsATurnEnd:
    def test_a_turn_that_asked_is_not_blocked(
        self,
        tmp_path: Path,
        isolated_marker: Path,
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
        isolated_marker: Path,
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
        isolated_marker: Path,
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

        first = decide(data=data, plan=None)
        record_block(session_id="s8")
        second = decide(data=data, plan=None)

        assert first.block is True
        assert second.block is False

    def test_an_unreadable_transcript_is_no_evidence(
        self,
        isolated_marker: Path,
    ) -> None:
        verdict = decide(
            data={"session_id": "s9", "transcript_path": "/nonexistent/transcript.jsonl"},
            plan=None,
        )

        assert verdict.block is False

    def test_a_missing_transcript_path_is_no_evidence(
        self,
        isolated_marker: Path,
    ) -> None:
        assert decide(data={"session_id": "s10"}, plan=None).block is False

    def test_a_corrupt_transcript_is_no_evidence(
        self,
        tmp_path: Path,
        isolated_marker: Path,
    ) -> None:
        """UnicodeDecodeError is a ValueError, so OSError alone misses it."""
        path = tmp_path / "binary.jsonl"
        path.write_bytes(b"\xff\xfe\x00\x01 not utf-8")

        verdict = decide(data={"session_id": "s13", "transcript_path": str(path)}, plan=None)

        assert verdict.block is False

    def test_a_turn_with_no_assistant_output_is_no_evidence(
        self,
        tmp_path: Path,
        isolated_marker: Path,
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

    def test_malformed_lines_are_skipped(self, tmp_path: Path, isolated_marker: Path) -> None:
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

        verdict = decide(data={"session_id": "s12", "transcript_path": str(path)}, plan=None)

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
        assert signal.at_phase_boundary is False

    def test_a_plan_without_tasks_yields_no_signal(self) -> None:
        assert task_signal(plan={"context": {}}).has_open_work is False

    def test_in_progress_counts_as_open(self) -> None:
        signal = task_signal(plan={"tasks": [{"subject": "Verify", "status": "in_progress"}]})

        assert signal.open_subjects == ("Verify",)

    def test_blank_subjects_are_dropped(self) -> None:
        signal = task_signal(plan={"tasks": [{"subject": "   ", "status": "pending"}]})

        assert signal.has_open_work is False

    def test_completed_phases_in_order_are_not_a_boundary(self) -> None:
        signal = task_signal(
            plan={
                "tasks": [
                    {"subject": "Phase 1: a", "status": "completed"},
                    {"subject": "Phase 2: b", "status": "completed"},
                ]
            }
        )

        assert signal.at_phase_boundary is False


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

    def test_a_fresh_session_was_not_blocked_recently(self, isolated_marker: Path) -> None:
        assert blocked_recently(session_id="fresh") is False

    def test_a_recorded_block_is_seen(self, isolated_marker: Path) -> None:
        record_block(session_id="seen")

        assert blocked_recently(session_id="seen") is True

    def test_the_cooldown_expires(self, isolated_marker: Path) -> None:
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
        isolated_marker: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The first block of a session is the expected case, not a fault."""
        assert blocked_recently(session_id="first") is False
        assert capsys.readouterr().err == ""


class TestWiringRecordsTheBlock:
    """``build_stop_verdict`` is the layer that turns a verdict into state."""

    @pytest.fixture()
    def no_plan(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "dev10x.hooks.session_dispatch._get_toplevel",
            lambda: None,
        )

    def test_a_block_is_returned_and_recorded_once(
        self,
        tmp_path: Path,
        isolated_marker: Path,
        no_plan: None,
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
        isolated_marker: Path,
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
        isolated_marker: Path,
        no_plan: None,
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
        isolated_marker: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO("{not json"))

        assert build_stop_verdict() is None

    def test_the_plan_feeds_the_steer(
        self,
        tmp_path: Path,
        isolated_marker: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
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
        monkeypatch.setattr(
            "dev10x.hooks.session_dispatch.read_plan_summary",
            lambda *, toplevel: {
                "plan": {"tasks": [{"subject": "Monitor CI", "status": "pending"}]}
            },
        )

        verdict = build_stop_verdict(data={"session_id": "w3", "transcript_path": transcript})

        assert verdict is not None
        assert "Monitor CI" in verdict.reason
