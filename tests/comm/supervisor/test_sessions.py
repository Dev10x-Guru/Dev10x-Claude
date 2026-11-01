"""Tests for merging probe output into one session view (GH-1692)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from dev10x.comm.skills.bus.maildir import SessionStatus
from dev10x.comm.supervisor.sessions import (
    ClaudeSession,
    HerdrPane,
    ProbeParseError,
    SessionView,
    merge_sessions,
    parse_claude_agents,
    parse_herdr_agents,
)
from tests.comm.supervisor.conftest import BUSY_ID, IDLE_ID, NOW, WAITING_ID


def _claude(*, status: str = "idle", name: str = "s1", session_id: str = "id-1") -> ClaudeSession:
    return ClaudeSession(
        session_id=session_id,
        pid=1,
        name=name,
        cwd="/w",
        status=status,
        waiting_for="",
    )


def _board(*, state: str, mailbox: str = "s1") -> SessionStatus:
    return SessionStatus(mailbox=mailbox, state=state, summary="Doing it.", updated=NOW)


class TestParseClaudeAgents:
    @pytest.fixture
    def sessions(self, claude_agents_json: str) -> dict[str, ClaudeSession]:
        return {
            session.session_id: session for session in parse_claude_agents(raw=claude_agents_json)
        }

    def test_reads_waiting_for(self, sessions: dict[str, ClaudeSession]) -> None:
        assert (sessions[WAITING_ID].status, sessions[WAITING_ID].waiting_for) == (
            "waiting",
            "permission prompt",
        )

    def test_missing_waiting_for_is_empty(self, sessions: dict[str, ClaudeSession]) -> None:
        assert sessions[BUSY_ID].waiting_for == ""

    def test_reads_started_at_from_epoch_millis(self, sessions: dict[str, ClaudeSession]) -> None:
        assert sessions[IDLE_ID].started_at == datetime.fromtimestamp(1793434339.051, tz=UTC)

    @pytest.mark.parametrize("raw", [None, "1793434339051", True], ids=["missing", "str", "bool"])
    def test_unusable_started_at_is_none(self, raw: object) -> None:
        entry = {"sessionId": "id-1", "startedAt": raw}

        assert parse_claude_agents(raw=json.dumps([entry]))[0].started_at is None

    def test_rejects_garbage(self) -> None:
        with pytest.raises(ProbeParseError, match="claude agents"):
            parse_claude_agents(raw="not json")

    def test_rejects_non_list(self) -> None:
        with pytest.raises(ProbeParseError, match="non-list"):
            parse_claude_agents(raw="{}")


class TestParseHerdrAgents:
    @pytest.fixture
    def panes(self, herdr_agents_json: str) -> list[HerdrPane]:
        return parse_herdr_agents(raw=herdr_agents_json)

    def test_keys_by_session_value(self, panes: list[HerdrPane]) -> None:
        assert {pane.session_id: pane.pane_id for pane in panes}[IDLE_ID] == "w12:p1"

    def test_reads_agent_name(self, panes: list[HerdrPane]) -> None:
        assert [pane.name for pane in panes] == ["", "mc-updates"]

    def test_skips_non_claude_agents(self, panes: list[HerdrPane]) -> None:
        assert [pane.pane_id for pane in panes] == ["w3:p1", "w12:p1"]

    def test_rejects_garbage(self) -> None:
        with pytest.raises(ProbeParseError, match="herdr agent list"):
            parse_herdr_agents(raw="[]")


class TestMergeSessions:
    @pytest.fixture
    def merged(self, claude_agents_json: str, herdr_agents_json: str) -> list[SessionView]:
        return merge_sessions(
            claude=parse_claude_agents(raw=claude_agents_json),
            panes=parse_herdr_agents(raw=herdr_agents_json),
            board=[
                SessionStatus(
                    mailbox="mc-updates",
                    state="done",
                    summary="Posted the update.",
                    updated=NOW,
                    callsign="status round",
                )
            ],
        )

    def test_joins_pane_by_session_id(self, merged: list[SessionView]) -> None:
        assert {view.session_id: view.pane_id for view in merged}[WAITING_ID] == "w3:p1"

    def test_keeps_session_without_pane(self, merged: list[SessionView]) -> None:
        assert {view.session_id: view.pane_id for view in merged}[BUSY_ID] == ""

    def test_carries_board_line(self, merged: list[SessionView]) -> None:
        view = {view.session_id: view for view in merged}[IDLE_ID]

        assert (view.callsign, view.summary, view.board_state) == (
            "status round",
            "Posted the update.",
            "done",
        )

    def test_needs_you_first(self, merged: list[SessionView]) -> None:
        assert [view.group for view in merged] == ["needs-you", "working", "done"]

    @pytest.mark.parametrize(
        ("status", "board_state", "group"),
        [
            ("waiting", "", "needs-you"),
            ("busy", "", "working"),
            ("idle", "needs-input", "needs-you"),
            ("idle", "working", "working"),
            ("idle", "", "done"),
        ],
    )
    def test_groups(self, status: str, board_state: str, group: str) -> None:
        board = [_board(state=board_state)] if board_state else []

        [view] = merge_sessions(claude=[_claude(status=status)], panes=[], board=board)

        assert view.group == group
