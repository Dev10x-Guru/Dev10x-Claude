from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from dev10x.domain.file_locks import locked_json_update

OPEN = "open"
ANSWERED = "answered"
DELIVERED = "delivered"
HOOK_CHANNEL = "hook"


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
    held_until: str = ""


def is_held(*, decision: Decision, now: datetime) -> bool:
    return (
        decision.state == OPEN
        and bool(decision.held_until)
        and datetime.fromisoformat(decision.held_until) > now
    )


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
        hold_seconds: float = 0,
        now: datetime | None = None,
    ) -> list[Decision]:
        at = now or datetime.now().astimezone()
        created = at.isoformat()
        held_until = (at + timedelta(seconds=hold_seconds)).isoformat() if hold_seconds > 0 else ""
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
                held_until=held_until,
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

    def collect(self, *, decision_ids: list[str]) -> dict[str, str] | None:
        with locked_json_update(self._path) as data:
            decisions = self._load(data=data)
            wanted = [decision for decision in decisions if decision.decision_id in decision_ids]
            ready = len(wanted) == len(set(decision_ids)) and all(
                decision.state == ANSWERED and decision.channel == HOOK_CHANNEL
                for decision in wanted
            )
            if not wanted or not ready:
                return None
            for decision in wanted:
                decision.state = DELIVERED
            self._save(data=data, decisions=decisions)
            return {decision.question: decision.answer for decision in wanted}

    def release(self, *, decision_ids: list[str]) -> None:
        with locked_json_update(self._path) as data:
            decisions = self._load(data=data)
            for decision in decisions:
                if decision.decision_id not in decision_ids:
                    continue
                decision.held_until = ""
                if decision.state == ANSWERED and decision.channel == HOOK_CHANNEL:
                    decision.state, decision.answer, decision.channel = OPEN, "", ""
            self._save(data=data, decisions=decisions)

    def reopen(self, *, decision_id: str) -> None:
        self._set_state(ids={decision_id}, from_states={ANSWERED}, to_state=OPEN)

    def mark_delivered(self, *, decision_id: str) -> None:
        self._set_state(ids={decision_id}, from_states={ANSWERED}, to_state=DELIVERED)

    def expire_for_session(self, *, session_id: str, created_before: datetime) -> None:
        with locked_json_update(self._path) as data:
            decisions = self._load(data=data)
            for decision in decisions:
                if (
                    decision.session_id == session_id
                    and decision.state == OPEN
                    and datetime.fromisoformat(decision.created) <= created_before
                ):
                    decision.state = DELIVERED
            self._save(data=data, decisions=decisions)

    def _set_state(self, *, ids: set[str], from_states: set[str], to_state: str) -> None:
        with locked_json_update(self._path) as data:
            decisions = self._load(data=data)
            for decision in decisions:
                if decision.decision_id in ids and decision.state in from_states:
                    decision.state = to_state
            self._save(data=data, decisions=decisions)
