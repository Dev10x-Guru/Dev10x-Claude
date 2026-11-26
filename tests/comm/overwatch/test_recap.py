"""Tests for the per-session recap shown on the Overwatch overview (GH-2020)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from dev10x.comm.overwatch.pending import ConversationEntry
from dev10x.comm.overwatch.recap import MAX_SAID_CHARS, RecapReader, SessionRecap, summarize
from dev10x.comm.overwatch.session_tasks import SessionTask

TASKS = [
    SessionTask(id="1", subject="Read the code", status="completed"),
    SessionTask(id="2", subject="Implement", status="in_progress", active_form="Implementing"),
    SessionTask(id="3", subject="Ship", status="pending"),
]
SAID = ConversationEntry(
    role="assistant",
    kind="text",
    text="Looked around.\n\nThe overview   renders;\nnext the tests.",
    at="2026-11-26T08:00:00Z",
)


class TestSummarize:
    def test_counts_tasks_and_names_the_current_one(self) -> None:
        recap = summarize(tasks=TASKS, said=None)

        assert (recap.tasks_done, recap.tasks_total, recap.current_task) == (1, 3, "Implementing")

    def test_current_task_falls_back_to_its_subject(self) -> None:
        recap = summarize(
            tasks=[SessionTask(id="1", subject="Implement", status="in_progress")], said=None
        )

        assert recap.current_task == "Implement"

    def test_keeps_the_last_paragraph_on_one_line(self) -> None:
        recap = summarize(tasks=[], said=SAID)

        assert (recap.last_said, recap.last_said_at) == (
            "The overview renders; next the tests.",
            "2026-11-26T08:00:00Z",
        )

    def test_clips_a_long_paragraph(self) -> None:
        said = ConversationEntry(role="assistant", kind="text", text="x" * 500)

        recap = summarize(tasks=[], said=said)

        assert (len(recap.last_said), recap.last_said.endswith("…")) == (MAX_SAID_CHARS + 1, True)

    def test_nothing_known_is_empty(self) -> None:
        assert summarize(tasks=[], said=None) == SessionRecap()


@pytest.fixture
def transcript(tmp_path: Path) -> Path:
    path = tmp_path / "sid.jsonl"
    path.write_text("{}\n")
    return path


class ConversationReader:
    def __init__(self, entries: list[ConversationEntry]) -> None:
        self.entries = entries
        self.calls = 0

    def __call__(self, *, session_id: str) -> list[ConversationEntry]:
        self.calls += 1
        return self.entries


@pytest.fixture
def conversation() -> ConversationReader:
    return ConversationReader(
        [
            SAID,
            ConversationEntry(role="assistant", kind="tool", text="pytest", tool="Bash"),
            ConversationEntry(role="user", kind="text", text="go on"),
        ]
    )


@pytest.fixture
def reader(transcript: Path, conversation: ConversationReader) -> RecapReader:
    return RecapReader(
        tasks_reader=lambda session_id: TASKS,
        conversation_reader=conversation,
        transcript_finder=lambda session_id: transcript,
    )


class TestRecapReader:
    def test_reads_the_last_thing_the_session_said(self, reader: RecapReader) -> None:
        recap = reader.read(session_id="sid")

        assert (recap.tasks_done, recap.last_said) == (1, "The overview renders; next the tests.")

    def test_unchanged_transcript_is_not_reread(
        self, reader: RecapReader, conversation: ConversationReader
    ) -> None:
        reader.read(session_id="sid")
        reader.read(session_id="sid")

        assert conversation.calls == 1

    def test_changed_transcript_is_reread(
        self, reader: RecapReader, conversation: ConversationReader, transcript: Path
    ) -> None:
        reader.read(session_id="sid")
        transcript.write_text("[]\n")
        os.utime(transcript, ns=(1, 1))
        reader.read(session_id="sid")

        assert conversation.calls == 2

    def test_transcript_gone_after_a_read_drops_what_was_said(
        self, reader: RecapReader, transcript: Path
    ) -> None:
        reader.read(session_id="sid")
        transcript.unlink()

        assert (reader.read(session_id="sid"), reader.said) == (
            SessionRecap(tasks_done=1, tasks_total=3, current_task="Implementing"),
            {},
        )

    def test_missing_transcript_has_nothing_said(self, conversation: ConversationReader) -> None:
        reader = RecapReader(
            tasks_reader=lambda session_id: [],
            conversation_reader=conversation,
            transcript_finder=lambda session_id: None,
        )

        assert (reader.read(session_id="sid"), conversation.calls) == (SessionRecap(), 0)

    def test_vanished_transcript_has_nothing_said(
        self, tmp_path: Path, conversation: ConversationReader
    ) -> None:
        reader = RecapReader(
            tasks_reader=lambda session_id: [],
            conversation_reader=conversation,
            transcript_finder=lambda session_id: tmp_path / "gone.jsonl",
        )

        assert reader.read(session_id="sid") == SessionRecap()
