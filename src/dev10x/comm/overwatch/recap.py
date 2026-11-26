from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from dev10x.comm.overwatch.pending import ConversationEntry, find_transcript, read_conversation
from dev10x.comm.overwatch.session_tasks import SessionTask, read_session_tasks

MAX_SAID_CHARS = 280

Fingerprint = tuple[int, int]


@dataclass(frozen=True)
class SessionRecap:
    tasks_done: int = 0
    tasks_total: int = 0
    current_task: str = ""
    last_said: str = ""
    last_said_at: str = ""


def _last_paragraph(*, text: str) -> str:
    paragraphs = [" ".join(block.split()) for block in text.split("\n\n")]
    said = next((block for block in reversed(paragraphs) if block), "")
    return said if len(said) <= MAX_SAID_CHARS else f"{said[:MAX_SAID_CHARS].rstrip()}…"


def _last_said(*, conversation: list[ConversationEntry]) -> ConversationEntry | None:
    return next(
        (
            entry
            for entry in reversed(conversation)
            if entry.role == "assistant" and entry.kind == "text" and entry.text.strip()
        ),
        None,
    )


def summarize(*, tasks: list[SessionTask], said: ConversationEntry | None) -> SessionRecap:
    current = next((task for task in tasks if task.status == "in_progress"), None)
    return SessionRecap(
        tasks_done=sum(task.status == "completed" for task in tasks),
        tasks_total=len(tasks),
        current_task=(current.active_form or current.subject) if current else "",
        last_said=_last_paragraph(text=said.text) if said else "",
        last_said_at=said.at if said else "",
    )


def _fingerprint(*, path: Path | None) -> Fingerprint | None:
    if path is None:
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


@dataclass
class RecapReader:
    tasks_reader: Callable[..., list[SessionTask]] = read_session_tasks
    conversation_reader: Callable[..., list[ConversationEntry]] = read_conversation
    transcript_finder: Callable[..., Path | None] = find_transcript
    said: dict[str, tuple[Fingerprint, ConversationEntry | None]] = field(default_factory=dict)

    def _said(self, *, session_id: str) -> ConversationEntry | None:
        fingerprint = _fingerprint(path=self.transcript_finder(session_id=session_id))
        if fingerprint is None:
            self.said.pop(session_id, None)
            return None
        cached = self.said.get(session_id)
        if cached is not None and cached[0] == fingerprint:
            return cached[1]
        entry = _last_said(conversation=self.conversation_reader(session_id=session_id))
        self.said[session_id] = (fingerprint, entry)
        return entry

    def read(self, *, session_id: str) -> SessionRecap:
        return summarize(
            tasks=self.tasks_reader(session_id=session_id),
            said=self._said(session_id=session_id),
        )
