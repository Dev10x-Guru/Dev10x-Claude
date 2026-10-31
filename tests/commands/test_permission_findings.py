"""Tests for `dev10x permission findings` (GH-1631)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from dev10x.commands.permission import permission_findings


def _write(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "findings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _finding(*, finding_id: str, severity: str) -> dict:
    return {
        "id": finding_id,
        "title": "t",
        "severity": severity,
        "file": "settings.local.json",
        "line": None,
        "current_rule": None,
        "proposed_fix": {"action": "add", "list": "deny", "rule": "Bash(sudo:*)"},
        "rationale": "r",
    }


@pytest.fixture
def valid_path(tmp_path: Path) -> Path:
    return _write(
        tmp_path,
        {
            "findings": [
                _finding(finding_id="m", severity="MEDIUM"),
                _finding(finding_id="c", severity="CRITICAL"),
            ]
        },
    )


def _invoke(*args: str) -> Result:
    return CliRunner().invoke(permission_findings, list(args))


def test_prints_all_findings_most_severe_first(valid_path: Path) -> None:
    result = _invoke(str(valid_path))

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert [f["id"] for f in data["findings"]] == ["c", "m"]
    assert data["excluded_by_severity"] == []


def test_severity_max_reports_excluded_ids(valid_path: Path) -> None:
    result = _invoke(str(valid_path), "--severity-max", "high")

    data = json.loads(result.output)
    assert [f["id"] for f in data["findings"]] == ["c"]
    assert data["excluded_by_severity"] == ["m"]


def test_invalid_block_emits_json_error(tmp_path: Path) -> None:
    result = _invoke(str(_write(tmp_path, {"findings": [{"id": "x"}]})))

    assert result.exit_code == 1
    assert "error" in json.loads(result.output)


def test_unparseable_file_emits_json_error(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")

    result = _invoke(str(path))

    assert result.exit_code == 1
    assert "cannot read" in json.loads(result.output)["error"]
