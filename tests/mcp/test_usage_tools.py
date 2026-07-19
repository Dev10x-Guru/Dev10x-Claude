"""Wire-contract tests for the usage_blocks MCP adapter (GH-878)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR
from dev10x.mcp import server_cli as cli_server


def _seed_recent_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "claude"
    monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(home))
    proj = home / "projects" / "repo"
    proj.mkdir(parents=True)
    ts = (datetime.now(UTC) - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    record = {
        "type": "assistant",
        "timestamp": ts,
        "requestId": "req_1",
        "costUSD": None,
        "message": {
            "id": "msg_1",
            "model": "claude-opus-4-8",
            "usage": {
                "input_tokens": 100,
                "output_tokens": 200,
                "cache_creation_input_tokens": 10,
                "cache_read_input_tokens": 20,
            },
        },
    }
    (proj / "s.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")


@pytest.mark.asyncio
async def test_usage_blocks_active_returns_wire_dict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_recent_block(tmp_path, monkeypatch)
    result = await cli_server.usage_blocks(active=True)
    assert "error" not in result
    assert result["pricingSource"] == "offline-estimate"
    assert len(result["blocks"]) == 1
    assert result["blocks"][0]["isActive"] is True


@pytest.mark.asyncio
async def test_usage_blocks_empty_home_returns_no_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(tmp_path / "empty-claude"))
    result = await cli_server.usage_blocks(active=True)
    assert "error" not in result
    assert result["blocks"] == []
