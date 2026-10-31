"""Tests for delivering supervisor answers (GH-1692)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from dev10x.comm.skills.bus.maildir import read_message
from dev10x.comm.supervisor.delivery import (
    ANSWER_PREFIX,
    deliver_keys,
    deliver_relay,
    keys_for_option,
    keys_for_permission,
)
from dev10x.comm.supervisor.probes import ProbeError


class RecordingSender:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error = error

    def __call__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        if self.error:
            raise self.error


@pytest.fixture
def log_path(tmp_path: Path) -> Path:
    return tmp_path / "actions.jsonl"


@pytest.mark.parametrize(("index", "keys"), [(0, ["1"]), (2, ["3"])])
def test_keys_for_option(index: int, keys: list[str]) -> None:
    assert keys_for_option(index=index) == keys


@pytest.mark.parametrize(("allow", "keys"), [(True, ["1"]), (False, ["esc"])])
def test_keys_for_permission(allow: bool, keys: list[str]) -> None:
    assert keys_for_permission(allow=allow) == keys


class TestDeliverKeys:
    def test_logs_after_send(self, log_path: Path) -> None:
        sender = RecordingSender()

        deliver_keys(
            pane_id="w3:p1",
            keys=["2"],
            confirmed_by="janusz",
            log_path=log_path,
            sender=sender,
        )
        record = json.loads(log_path.read_text(encoding="utf-8"))

        assert (sender.calls, record["action"], record["confirmed_by"], record["detail"]) == (
            [{"pane_id": "w3:p1", "keys": ["2"]}],
            "keys",
            "janusz",
            "2",
        )

    def test_does_not_log_when_send_fails(self, log_path: Path) -> None:
        sender = RecordingSender(error=ProbeError("herdr exited 1"))

        with pytest.raises(ProbeError):
            deliver_keys(
                pane_id="w3:p1",
                keys=["1"],
                confirmed_by="janusz",
                log_path=log_path,
                sender=sender,
            )

        assert not log_path.exists()


class TestDeliverRelay:
    @pytest.fixture
    def message(self, tmp_path: Path, log_path: Path) -> tuple[dict[str, str], str]:
        path = deliver_relay(
            bus_root=tmp_path / "bus",
            relay_mailbox="supervisor-relay",
            session_name="push to tlak",
            session_id="b5eb296e",
            decision_id="b5eb296e-1234",
            answer="Relay (Recommended)",
            confirmed_by="janusz",
            log_path=log_path,
        )
        assert path.parent == tmp_path / "bus" / "supervisor-relay" / "new"
        return read_message(message=path)

    def test_body_carries_prefix(self, message: tuple[dict[str, str], str]) -> None:
        assert message[1].strip() == ANSWER_PREFIX + "Relay (Recommended)"

    def test_headers_name_the_target(self, message: tuple[dict[str, str], str]) -> None:
        headers = message[0]

        assert (
            headers["subject"],
            headers["to-session"],
            headers["session-id"],
            headers["decision-id"],
        ) == ("answer b5eb296e-1234", "push to tlak", "b5eb296e", "b5eb296e-1234")

    def test_logged(self, message: tuple[dict[str, str], str], log_path: Path) -> None:
        assert json.loads(log_path.read_text(encoding="utf-8"))["action"] == "relay"
