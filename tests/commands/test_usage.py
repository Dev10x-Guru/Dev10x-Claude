from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner

from dev10x.commands.usage import usage
from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR
from dev10x.domain.common.result import err


def _recent_iso(minutes_ago: int = 1) -> str:
    moment = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    return moment.isoformat().replace("+00:00", "Z")


def _seed_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    model: str = "claude-opus-4-8",
    with_record: bool = True,
) -> None:
    home = tmp_path / "claude"
    monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(home))
    proj = home / "projects" / "repo"
    proj.mkdir(parents=True)
    if with_record:
        record = {
            "type": "assistant",
            "timestamp": _recent_iso(),
            "requestId": "req_1",
            "costUSD": None,
            "message": {
                "id": "msg_1",
                "model": model,
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 200,
                    "cache_creation_input_tokens": 10,
                    "cache_read_input_tokens": 20,
                },
            },
        }
        (proj / "s.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")


def test_blocks_active_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_home(tmp_path, monkeypatch)
    result = CliRunner().invoke(usage, ["blocks", "--active", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert len(payload["blocks"]) == 1
    assert payload["blocks"][0]["isActive"] is True


def test_blocks_all_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_home(tmp_path, monkeypatch)
    result = CliRunner().invoke(usage, ["blocks", "--all", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert len(payload["blocks"]) == 1


def test_blocks_human_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_home(tmp_path, monkeypatch)
    result = CliRunner().invoke(usage, ["blocks", "--active"])
    assert result.exit_code == 0
    assert "active" in result.output
    assert "tokens:" in result.output
    assert "cost≈" in result.output
    assert "remaining=" in result.output


def test_blocks_no_data_human(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_home(tmp_path, monkeypatch, with_record=False)
    result = CliRunner().invoke(usage, ["blocks", "--active"])
    assert result.exit_code == 0
    assert "No usage blocks found." in result.output


def test_blocks_unpriced_model_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_home(tmp_path, monkeypatch, model="claude-fable-5")
    result = CliRunner().invoke(usage, ["blocks", "--active"])
    assert result.exit_code == 0
    assert "unpriced models" in result.output


def test_blocks_error_exits_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "dev10x.domain.usage.blocks_report",
        lambda **_kwargs: err("boom"),
    )
    result = CliRunner().invoke(usage, ["blocks", "--active", "--json"])
    assert result.exit_code == 1
    assert "boom" in result.output
