"""Tests for the raw-bq-allow doctor strategy (GH-1633)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.core.skills.doctor.registry import load_strategies
from dev10x.core.skills.doctor.strategies import raw_bq_allow
from dev10x.core.skills.doctor.strategy import Context


def _settings(*, tmp_path: Path, allow: list[str]) -> Path:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"permissions": {"allow": allow}}))
    return path


@pytest.mark.parametrize(
    ("rule", "flagged"),
    [
        pytest.param("Bash(bq:*)", True, id="any-bq"),
        pytest.param("Bash(bq *)", True, id="space-wildcard"),
        pytest.param("Bash(bq)", True, id="bare"),
        pytest.param("Bash(bq query:*)", True, id="query"),
        pytest.param("Bash(bq query *)", True, id="query-space"),
        pytest.param("Bash(bq rm:*)", True, id="write-verb"),
        pytest.param("Bash(bq ls:*)", False, id="ls"),
        pytest.param("Bash(bq show *)", False, id="show"),
        pytest.param("Bash(bqx:*)", False, id="other-program"),
        pytest.param("Read(bq:*)", False, id="other-tool"),
        pytest.param("mcp__plugin_dev10x_db__bq_query", False, id="mcp-tool"),
    ],
)
def test_runs_raw_bq(rule: str, flagged: bool) -> None:
    assert raw_bq_allow.runs_raw_bq(rule=rule) is flagged


class TestDetect:
    def test_flags_each_raw_bq_allow(self, tmp_path: Path) -> None:
        path = _settings(
            tmp_path=tmp_path, allow=["Bash(bq query:*)", "Bash(bq ls:*)", "Bash(git status)"]
        )

        findings = raw_bq_allow.detect(Context(settings_paths=(path,)))

        assert [(f.strategy_id, f.severity, f.location) for f in findings] == [
            ("raw-bq-allow", "suggestion", str(path))
        ]
        assert "Bash(bq query:*)" in findings[0].proposed_fix

    def test_silent_without_bq_rules(self, tmp_path: Path) -> None:
        path = _settings(tmp_path=tmp_path, allow=["Bash(git status)"])

        assert raw_bq_allow.detect(Context(settings_paths=(path,))) == []

    def test_skips_a_missing_file(self, tmp_path: Path) -> None:
        assert raw_bq_allow.detect(Context(settings_paths=(tmp_path / "absent.json",))) == []


def test_remediation_moves_the_rule_to_deny(tmp_path: Path) -> None:
    path = _settings(tmp_path=tmp_path, allow=["Bash(bq:*)"])
    finding = raw_bq_allow.detect(Context(settings_paths=(path,)))[0]

    remediation = raw_bq_allow.remediate(finding)

    assert (remediation.kind, remediation.target) == ("edit_settings", str(path))
    assert remediation.action["remove"] == {"permissions.allow": "Bash(bq:*)"}
    assert remediation.action["add"] == {"permissions.deny": "Bash(bq:*)"}


def test_is_registered() -> None:
    assert "raw-bq-allow" in {strategy.id for strategy in load_strategies()}
