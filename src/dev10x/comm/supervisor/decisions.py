from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from dev10x.domain.file_locks import locked_json_update

OPEN = "open"
ANSWERED = "answered"
DELIVERED = "delivered"


@dataclass
class Decision:
    decision_id: str
    session_id: str
    cwd: str
    question: str
    header: str
    options: list[str]
    multi_select: bool
    created: str
    state: str = OPEN
    answer: str = ""
    channel: str = ""


def _option_labels(*, question: dict[str, Any]) -> list[str]:
    return [
        str(option.get("label", "")) if isinstance(option, dict) else str(option)
        for option in question.get("options", [])
    ]


class DecisionStore:
    def __init__(self, *, path: Path) -> None:
        self._path = path

    def _load(self, *, data: dict[str, Any]) -> list[Decision]:
        return [Decision(**entry) for entry in data.get("decisions", [])]

    def _save(self, *, data: dict[str, Any], decisions: list[Decision]) -> None:
        data["decisions"] = [asdict(decision) for decision in decisions]

    def add_from_hook(
        self,
        *,
        session_id: str,
        cwd: str,
        questions: list[dict[str, Any]],
    ) -> list[Decision]:
        created = datetime.now().astimezone().isoformat(timespec="seconds")
        added = [
            Decision(
                decision_id=f"{session_id[:8]}-{uuid4().hex[:8]}",
                session_id=session_id,
                cwd=cwd,
                question=str(question.get("question", "")),
                header=str(question.get("header", "")),
                options=_option_labels(question=question),
                multi_select=bool(question.get("multiSelect", False)),
                created=created,
            )
            for question in questions
        ]
        with locked_json_update(self._path) as data:
            self._save(data=data, decisions=self._load(data=data) + added)
        return added

    def all(self) -> list[Decision]:
        if not self._path.exists():
            return []
        return self._load(data=json.loads(self._path.read_text(encoding="utf-8")))

    def open_for(self, *, session_id: str) -> list[Decision]:
        return [
            decision
            for decision in self.all()
            if decision.session_id == session_id and decision.state == OPEN
        ]

    def get(self, *, decision_id: str) -> Decision | None:
        return next(
            (decision for decision in self.all() if decision.decision_id == decision_id),
            None,
        )

    def answer(self, *, decision_id: str, answer: str, channel: str) -> Decision | None:
        with locked_json_update(self._path) as data:
            decisions = self._load(data=data)
            target = next(
                (
                    decision
                    for decision in decisions
                    if decision.decision_id == decision_id and decision.state == OPEN
                ),
                None,
            )
            if target is None:
                return None
            target.state = ANSWERED
            target.answer = answer
            target.channel = channel
            self._save(data=data, decisions=decisions)
            return target

    def reopen(self, *, decision_id: str) -> None:
        self._set_state(ids={decision_id}, from_states={ANSWERED}, to_state=OPEN)

    def mark_delivered(self, *, decision_id: str) -> None:
        self._set_state(ids={decision_id}, from_states={ANSWERED}, to_state=DELIVERED)

    def expire_for_session(self, *, session_id: str) -> None:
        with locked_json_update(self._path) as data:
            decisions = self._load(data=data)
            for decision in decisions:
                if decision.session_id == session_id and decision.state == OPEN:
                    decision.state = DELIVERED
            self._save(data=data, decisions=decisions)

    def _set_state(self, *, ids: set[str], from_states: set[str], to_state: str) -> None:
        with locked_json_update(self._path) as data:
            decisions = self._load(data=data)
            for decision in decisions:
                if decision.decision_id in ids and decision.state in from_states:
                    decision.state = to_state
            self._save(data=data, decisions=decisions)
