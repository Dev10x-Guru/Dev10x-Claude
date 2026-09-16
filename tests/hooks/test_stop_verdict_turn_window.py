"""GH-1334: the turn window has to contain the widget it looks for.

``asked_a_question`` scans the turn for an ``AskUserQuestion`` tool_use
block, and ``_read_turn`` walks back to the first user entry. But a tool
result *is* a user entry — 36 of the 38 user entries in a captured
transcript were ``tool_result`` blocks and only 2 were typed messages —
so the window stopped at the last tool call rather than the last human
message.

Every ``AskUserQuestion`` is followed by its own tool result, so the call
was always on the far side of that boundary. The audit log measured the
consequence: ``asked`` fired 0 times in 159 records while ``blocked``
fired 76. Complying with the gate's own steer could not satisfy it.

The repair is a predicate change, not a wider scan: a user entry whose
content is nothing but tool results is not a turn boundary. That
restores the invariant ``_read_turn`` documents and keeps its cost tied
to one turn.

GH-1336 finishes it. A widget *answer* is a tool result too, so after
GH-1334 the window for every turn following a click still held the
original call and the gate resolved ``asked`` until the supervisor next
typed — under-firing exactly where step 3 of the bug report says. An
answer now ends the turn it belongs to, on either of two discriminators
captured from a live transcript: the top-level ``toolUseResult``
carrying ``questions`` beside ``answers``, or a ``tool_use_id`` matching
an ``AskUserQuestion`` call earlier in the same turn.
"""

from __future__ import annotations

import json
from pathlib import Path

from dev10x.hooks.stop_verdict import (
    StopSignal,
    _is_user,
    _read_turn,
    _read_turn_and_boundary,
    asked_a_question,
    decide,
)


def _typed(*, text: str = "go", uuid: str = "u1") -> dict:
    """A message the supervisor actually typed."""
    return {"type": "user", "uuid": uuid, "message": {"role": "user", "content": text}}


def _tool_result(*, text: str = "ok") -> dict:
    """A user entry that is only a tool result — the shape that misled the walk."""
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "content": [{"type": "text", "text": text}]}],
        },
    }


def _assistant(*, blocks: list[dict]) -> dict:
    return {"type": "assistant", "message": {"role": "assistant", "content": blocks}}


def _ask(*, call_id: str = "toolu_ask") -> dict:
    return {"type": "tool_use", "id": call_id, "name": "AskUserQuestion", "input": {}}


def _widget_answer(*, text: str = "Yes, keep going") -> dict:
    """A widget answer as the harness writes one (GH-1336).

    Shape captured from a live transcript rather than invented: the
    entry carries a top-level ``toolUseResult`` holding ``questions``
    beside ``answers``, which no other tool result in that file did.
    """
    return {
        "type": "user",
        "uuid": "answer",
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_ask", "content": text},
            ],
        },
        "toolUseResult": {"questions": [{"question": "Anything open?"}], "answers": [text]},
    }


def _bare_widget_answer(*, text: str = "Yes, keep going") -> dict:
    """The same answer with only the wire-protocol discriminator left.

    ``toolUseResult`` is written by the transcript writer, not promised
    by the protocol, so the fallback has to stand on its own.
    """
    return {
        "type": "user",
        "uuid": "answer",
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_ask", "content": text},
            ],
        },
    }


def _text(*, text: str) -> dict:
    return {"type": "text", "text": text}


def _transcript(*, tmp_path: Path, entries: list[dict]) -> str:
    path = tmp_path / "transcript.jsonl"
    path.write_text("\n".join(json.dumps(entry) for entry in entries), encoding="utf-8")
    return str(path)


def _unanswered_widget() -> list[dict]:
    """A turn that ends *on* the widget — the state the gate must not touch."""
    return [
        _typed(),
        _assistant(blocks=[_text(text="Two options here.")]),
        _assistant(blocks=[_ask()]),
    ]


def _answered_widget(*, answer: dict | None = None) -> list[dict]:
    """The sequence the bug report captured: ask, answer, keep working.

    Entry order matches the real transcript — the ``tool_use`` block sits
    immediately before the user entry carrying its result.
    """
    return [
        _typed(),
        _assistant(blocks=[_ask()]),
        answer or _widget_answer(),
        _assistant(blocks=[_text(text="Carrying on, then.")]),
    ]


class TestATurnThatAskedIsRecognised:
    """The measured zero: ``asked`` never fired, so the gate was unsatisfiable."""

    def test_a_turn_ending_on_the_widget_still_counts(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        transcript = _transcript(tmp_path=tmp_path, entries=_unanswered_widget())

        verdict = decide(
            data={"session_id": "win1", "transcript_path": transcript},
            plan=None,
        )

        assert verdict.block is False
        assert verdict.signal == StopSignal.ASKED

    def test_the_window_reaches_past_ordinary_tool_traffic(self, tmp_path: Path) -> None:
        """GH-1334's invariant, restated on a result that answers no widget."""
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=[
                _typed(),
                _assistant(blocks=[_ask()]),
                _tool_result(),
                _assistant(blocks=[_text(text="Still waiting on you.")]),
            ],
        )

        assert asked_a_question(entries=_read_turn(transcript_path=transcript)) is True

    def test_several_tool_calls_do_not_shrink_the_turn(self, tmp_path: Path) -> None:
        """A working turn is mostly tool traffic; none of it is a boundary."""
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=[
                _typed(),
                _assistant(blocks=[_ask()]),
                _tool_result(),
                _tool_result(),
                _tool_result(),
                _assistant(blocks=[_text(text="Done.")]),
            ],
        )

        assert asked_a_question(entries=_read_turn(transcript_path=transcript)) is True


class TestAnAnsweredWidgetEndsTheTurn:
    """GH-1336: the gate under-fired on every turn after a click.

    A **false pass** (the bug) lets a session drift: the agent ends turn
    after turn with no widget and nothing objects, because a widget the
    supervisor answered hours ago is still inside the window. A **false
    block** is the opposite failure and the more expensive one — it
    would re-arm the gate on a turn that legitimately ended on a widget,
    so the steer would demand a question that is already on screen.
    """

    def test_a_turn_after_an_answered_widget_is_blocked(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        transcript = _transcript(tmp_path=tmp_path, entries=_answered_widget())

        verdict = decide(
            data={"session_id": "win-1336", "transcript_path": transcript},
            plan={"tasks": [{"subject": "Ship it", "status": "completed"}]},
        )

        assert verdict.block is True
        assert verdict.signal == StopSignal.BLOCKED

    def test_the_tool_use_id_alone_is_enough(self, tmp_path: Path, isolated_markers: Path) -> None:
        """The fallback stands without the transcript writer's richer key."""
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=_answered_widget(answer=_bare_widget_answer()),
        )

        verdict = decide(
            data={"session_id": "win-1336-bare", "transcript_path": transcript},
            plan={"tasks": [{"subject": "Ship it", "status": "completed"}]},
        )

        assert verdict.block is True

    def test_the_answer_becomes_the_boundary(self, tmp_path: Path) -> None:
        transcript = _transcript(tmp_path=tmp_path, entries=_answered_widget())

        turn, boundary = _read_turn_and_boundary(transcript_path=transcript)

        assert asked_a_question(entries=turn) is False
        assert len(turn) == 1
        assert boundary is not None
        assert boundary["uuid"] == "answer"

    def test_a_widget_asked_after_the_answer_still_counts(self, tmp_path: Path) -> None:
        """Only the *last* answer cuts, so a fresh question survives the cut."""
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=[
                *_answered_widget(),
                _assistant(blocks=[_ask(call_id="toolu_second")]),
            ],
        )

        assert asked_a_question(entries=_read_turn(transcript_path=transcript)) is True

    def test_an_answer_with_nothing_after_it_leaves_the_turn_alone(self, tmp_path: Path) -> None:
        """Cutting to nothing would report ``NO_TRANSCRIPT`` and lie about why."""
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=[_typed(), _assistant(blocks=[_ask()]), _widget_answer()],
        )

        turn, boundary = _read_turn_and_boundary(transcript_path=transcript)

        assert len(turn) == 2
        assert boundary is not None
        assert boundary["uuid"] == "u1"

    def test_a_result_naming_an_unrelated_call_is_not_an_answer(self, tmp_path: Path) -> None:
        """A ``tool_use_id`` from any other tool must not cut the turn."""
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=[
                _typed(),
                _assistant(blocks=[_ask()]),
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": [
                            {"type": "tool_result", "tool_use_id": "toolu_bash", "content": "ok"}
                        ],
                    },
                },
                _assistant(blocks=[_text(text="Still waiting on you.")]),
            ],
        )

        assert asked_a_question(entries=_read_turn(transcript_path=transcript)) is True

    def test_a_half_shaped_tool_use_result_is_not_an_answer(self, tmp_path: Path) -> None:
        """``questions`` without ``answers`` is not the captured shape."""
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=[
                _typed(),
                _assistant(blocks=[_ask()]),
                {
                    "type": "user",
                    "message": {"role": "user", "content": [{"type": "tool_result"}]},
                    "toolUseResult": {"questions": []},
                },
                _assistant(blocks=[_text(text="Still waiting on you.")]),
            ],
        )

        assert asked_a_question(entries=_read_turn(transcript_path=transcript)) is True

    def test_standby_given_as_a_widget_answer_still_parks_the_gate(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        """The answer that parks the gate is now the boundary carrying it."""
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=_answered_widget(
                answer=_widget_answer(text="On standby — not waiting on you")
            ),
        )

        verdict = decide(
            data={"session_id": "win-standby", "transcript_path": transcript},
            plan={"tasks": [{"subject": "Ship it", "status": "completed"}]},
        )

        assert verdict.block is False
        assert verdict.signal == StopSignal.STANDBY


class TestTheBoundaryIsStillTheSupervisor:
    """The fix must not widen the scan to the whole session."""

    def test_a_typed_message_still_ends_the_walk(self, tmp_path: Path) -> None:
        """An ask the supervisor already answered does not cover a later turn."""
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=[
                _typed(text="a", uuid="u1"),
                _assistant(blocks=[_ask()]),
                _typed(text="b", uuid="u2"),
                _assistant(blocks=[_text(text="Done.")]),
            ],
        )

        turn, boundary = _read_turn_and_boundary(transcript_path=transcript)

        assert asked_a_question(entries=turn) is False
        assert len(turn) == 1
        assert boundary is not None
        assert boundary["uuid"] == "u2"

    def test_the_boundary_is_the_typed_message_not_the_tool_result(self, tmp_path: Path) -> None:
        """Standby is scoped to this entry, so it has to be the human's word."""
        transcript = _transcript(
            tmp_path=tmp_path,
            entries=[
                _typed(uuid="typed"),
                _tool_result(),
                _assistant(blocks=[_text(text="Done.")]),
            ],
        )

        _, boundary = _read_turn_and_boundary(transcript_path=transcript)

        assert boundary is not None
        assert boundary["uuid"] == "typed"


class TestWhatCountsAsAUserMessage:
    def test_a_tool_result_only_entry_is_not_a_boundary(self) -> None:
        assert _is_user(entry=_tool_result()) is False

    def test_a_typed_message_is_a_boundary(self) -> None:
        assert _is_user(entry=_typed()) is True

    def test_prose_blocks_are_a_boundary(self) -> None:
        entry = {"type": "user", "message": {"role": "user", "content": [_text(text="hi")]}}

        assert _is_user(entry=entry) is True

    def test_a_tool_result_carrying_prose_alongside_it_is_a_boundary(self) -> None:
        """A supervisor who types while a tool returns has still spoken."""
        entry = {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {"type": "tool_result", "content": "ok"},
                    _text(text="also, stop after this"),
                ],
            },
        }

        assert _is_user(entry=entry) is True

    def test_an_assistant_entry_is_never_a_boundary(self) -> None:
        assert _is_user(entry=_assistant(blocks=[_text(text="hi")])) is False

    def test_the_role_key_is_honoured_too(self) -> None:
        """Some transcript shapes carry `role` rather than `type`."""
        assert _is_user(entry={"role": "user", "content": "go"}) is True
