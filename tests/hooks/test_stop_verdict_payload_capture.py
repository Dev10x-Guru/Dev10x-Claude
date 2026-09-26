"""Record the Stop payload's shape instead of guessing it (GH-1347)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.hooks.session_dispatch import build_stop_verdict
from dev10x.hooks.stop_verdict import PAYLOAD_KEYS_FLAG, payload_capture

SUBAGENT_TRANSCRIPT = "/p/-work/0423993e/subagents/agent-a0932d5778dc9cc06.jsonl"
PAYLOAD = {
    "session_id": "s-1",
    "transcript_path": SUBAGENT_TRANSCRIPT,
    "hook_event_name": "Stop",
    "stop_hook_active": True,
    "last_assistant_message": "a report that must not reach the log",
}


class TestPayloadCapture:
    def test_nothing_is_captured_without_the_flag(self) -> None:
        assert payload_capture(data=PAYLOAD, env={}) == {}

    @pytest.mark.parametrize("value", ["", "0", "no", "false"])
    def test_a_falsy_flag_captures_nothing(self, value: str) -> None:
        assert payload_capture(data=PAYLOAD, env={PAYLOAD_KEYS_FLAG: value}) == {}

    @pytest.mark.parametrize("value", ["1", "true", "YES"])
    def test_the_flag_records_the_sorted_keys(self, value: str) -> None:
        captured = payload_capture(data=PAYLOAD, env={PAYLOAD_KEYS_FLAG: value})

        assert captured["payload_keys"] == (
            "hook_event_name,last_assistant_message,session_id,stop_hook_active,transcript_path"
        )

    def test_values_are_never_recorded(self) -> None:
        captured = payload_capture(data=PAYLOAD, env={PAYLOAD_KEYS_FLAG: "1"})

        assert "must not reach the log" not in " ".join(captured.values())

    def test_the_record_carries_what_separates_the_two_explanations(self) -> None:
        captured = payload_capture(data=PAYLOAD, env={PAYLOAD_KEYS_FLAG: "1"})

        assert captured["hook_event_name"] == "Stop"
        assert captured["session_id"] == "s-1"
        assert captured["transcript_layout"] == "subagent"

    def test_a_session_transcript_reads_as_a_session(self) -> None:
        captured = payload_capture(
            data={"transcript_path": "/p/-work/0423993e.jsonl"},
            env={PAYLOAD_KEYS_FLAG: "1"},
        )

        assert captured["transcript_layout"] == "session"
        assert captured["hook_event_name"] == ""


class TestWiring:
    def test_the_capture_reaches_the_audit_record(
        self,
        isolated_markers: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        recorded: dict[str, str] = {}

        def _capture(*, rule_id: str, reason: str, extra: dict[str, str] | None = None) -> None:
            recorded.update(rule_id=rule_id, reason=reason, **(extra or {}))

        monkeypatch.setattr("dev10x.hooks.session_dispatch.set_decision_attribution", _capture)
        monkeypatch.setattr("dev10x.hooks.session_dispatch._get_toplevel", lambda: None)
        monkeypatch.setenv(PAYLOAD_KEYS_FLAG, "1")

        build_stop_verdict(data={"session_id": "w-1", "stop_hook_active": True})

        assert recorded["payload_keys"] == "session_id,stop_hook_active"
        assert recorded["session_id"] == "w-1"
