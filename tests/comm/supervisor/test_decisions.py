"""Tests for the supervisor decision queue (GH-1692)."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from dev10x.comm.supervisor import paths
from dev10x.comm.supervisor.decisions import (
    ANSWERED,
    DELIVERED,
    OPEN,
    Decision,
    DecisionStore,
)

SESSION = "4f603efb-db56-4360-8539-e8520155ef1e"
LATER = datetime.now().astimezone() + timedelta(days=1)
EARLIER = datetime.now().astimezone() - timedelta(days=1)
QUESTIONS: list[dict[str, Any]] = [
    {
        "question": "Which hub?",
        "header": "Hub",
        "multiSelect": False,
        "options": [{"label": "Relay (Recommended)"}, {"label": "mc-updates"}],
    },
    {"question": "File the issue?", "header": "Ticket", "options": ["Yes", "No"]},
]


@pytest.fixture
def store(tmp_path: Path) -> DecisionStore:
    return DecisionStore(path=tmp_path / "decisions.json")


@pytest.fixture
def added(store: DecisionStore) -> list[Decision]:
    return store.add_from_hook(session_id=SESSION, cwd="/w", questions=QUESTIONS)


class TestAdd:
    def test_one_decision_per_question(self, added: list[Decision]) -> None:
        assert [(decision.question, decision.options) for decision in added] == [
            ("Which hub?", ["Relay (Recommended)", "mc-updates"]),
            ("File the issue?", ["Yes", "No"]),
        ]

    def test_ids_carry_session_prefix(self, added: list[Decision]) -> None:
        assert all(decision.decision_id.startswith("4f603efb-") for decision in added)

    def test_persisted(self, store: DecisionStore, added: list[Decision]) -> None:
        assert [decision.state for decision in store.open_for(session_id=SESSION)] == [
            OPEN,
            OPEN,
        ]

    def test_missing_file_is_empty(self, store: DecisionStore) -> None:
        assert store.all() == []


class TestAnswer:
    def test_answer_is_idempotent(self, store: DecisionStore, added: list[Decision]) -> None:
        decision_id = added[0].decision_id

        store.answer(decision_id=decision_id, answer="mc-updates", channel="keys")
        second = store.answer(decision_id=decision_id, answer="Relay", channel="relay")
        stored = store.get(decision_id=decision_id)

        assert (second, stored and (stored.state, stored.answer, stored.channel)) == (
            None,
            (ANSWERED, "mc-updates", "keys"),
        )

    def test_answer_unknown_returns_none(self, store: DecisionStore) -> None:
        assert store.answer(decision_id="nope", answer="x", channel="keys") is None

    def test_get_unknown_returns_none(self, store: DecisionStore, added: list[Decision]) -> None:
        assert store.get(decision_id="nope") is None

    def test_mark_delivered(self, store: DecisionStore, added: list[Decision]) -> None:
        decision_id = added[0].decision_id
        store.answer(decision_id=decision_id, answer="x", channel="keys")

        store.mark_delivered(decision_id=decision_id)

        assert store.get(decision_id=decision_id).state == DELIVERED  # type: ignore[union-attr]

    def test_reopen_after_failed_delivery(
        self,
        store: DecisionStore,
        added: list[Decision],
    ) -> None:
        decision_id = added[0].decision_id
        store.answer(decision_id=decision_id, answer="x", channel="keys")

        store.reopen(decision_id=decision_id)

        assert store.get(decision_id=decision_id).state == OPEN  # type: ignore[union-attr]


class TestExpire:
    def test_closes_only_that_session(self, store: DecisionStore, added: list[Decision]) -> None:
        other = store.add_from_hook(session_id="other-session", cwd="/o", questions=QUESTIONS[:1])

        store.expire_for_session(session_id=SESSION, created_before=LATER)

        assert {decision.decision_id: decision.state for decision in store.all()} == {
            added[0].decision_id: DELIVERED,
            added[1].decision_id: DELIVERED,
            other[0].decision_id: OPEN,
        }

    def test_keeps_decisions_newer_than_the_cutoff(
        self,
        store: DecisionStore,
        added: list[Decision],
    ) -> None:
        store.expire_for_session(session_id=SESSION, created_before=EARLIER)

        assert {decision.state for decision in store.all()} == {OPEN}


class TestPaths:
    def test_state_files_live_under_config_home(self, config_home: Path) -> None:
        assert [
            paths.token_path(),
            paths.decisions_path(),
            paths.actions_log_path(),
        ] == [
            config_home / "supervisor" / "token",
            config_home / "supervisor" / "decisions.json",
            config_home / "supervisor" / "actions.jsonl",
        ]
