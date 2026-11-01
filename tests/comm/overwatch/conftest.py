"""Fixtures for the supervisor daemon (GH-1692), shaped like live probe output."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from dev10x.domain.dev10x_paths import CONFIG_HOME_ENV_VAR, Dev10xConfigDir

NOW = datetime(2026, 10, 31, 12, 0, 0, tzinfo=UTC)

WAITING_ID = "4f603efb-db56-4360-8539-e8520155ef1e"
BUSY_ID = "db8cecc9-1bda-42a1-ba7a-4488b6cc1021"
IDLE_ID = "0c02333f-bd95-403f-b8c4-6807b4b9d86f"

CLAUDE_AGENTS = [
    {
        "pid": 36667,
        "cwd": "/home/janusz/KB",
        "kind": "interactive",
        "startedAt": 1793434347831,
        "sessionId": WAITING_ID,
        "name": "kb-84",
        "status": "waiting",
        "waitingFor": "permission prompt",
    },
    {
        "pid": 29810,
        "cwd": "/work/dx/Dev10x-Claude",
        "kind": "interactive",
        "startedAt": 1793434341530,
        "sessionId": BUSY_ID,
        "name": "dev10x-claude-44",
        "status": "busy",
    },
    {
        "pid": 26316,
        "cwd": "/work/tt/tt-mission-control",
        "kind": "interactive",
        "startedAt": 1793434339051,
        "sessionId": IDLE_ID,
        "name": "mc-updates",
        "status": "idle",
    },
]


def _herdr_agent(
    *,
    agent: str,
    session_id: str,
    pane_id: str,
    status: str,
    name: str = "",
) -> dict[str, object]:
    entry: dict[str, object] = {
        "agent": agent,
        "agent_session": {"agent": agent, "kind": "id", "value": session_id},
        "agent_status": status,
        "pane_id": pane_id,
        "terminal_title": f"title {pane_id}",
    }
    return {**entry, "name": name} if name else entry


HERDR_AGENTS = {
    "id": "cli:agent:list",
    "result": {
        "agents": [
            _herdr_agent(agent="claude", session_id=WAITING_ID, pane_id="w3:p1", status="blocked"),
            _herdr_agent(
                agent="claude",
                session_id=IDLE_ID,
                pane_id="w12:p1",
                status="done",
                name="mc-updates",
            ),
            _herdr_agent(agent="codex", session_id="codex-1", pane_id="w9:p1", status="idle"),
        ]
    },
}


@pytest.fixture
def claude_agents_json() -> str:
    return json.dumps(CLAUDE_AGENTS)


@pytest.fixture
def herdr_agents_json() -> str:
    return json.dumps(HERDR_AGENTS)


@pytest.fixture
def config_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    home = tmp_path / "config"
    monkeypatch.setenv(CONFIG_HOME_ENV_VAR, str(home))
    Dev10xConfigDir.reset_cache()
    yield home
    Dev10xConfigDir.reset_cache()
