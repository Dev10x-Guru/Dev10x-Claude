"""Tests for the missing-linear-mcp-allow doctor strategy (GH-204)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.skills.doctor.strategies import missing_linear_mcp_allow
from dev10x.skills.doctor.strategy import Context


@pytest.fixture()
def settings_with_partial_linear(tmp_path: Path) -> Path:
    """A project that has approved a few Linear tools but lacks the baseline."""
    path = tmp_path / "settings.local.json"
    path.write_text(
        json.dumps(
            {
                "permissions": {
                    "allow": [
                        "mcp__claude_ai_Linear__get_issue",
                        "Bash(gh pr view:*)",
                    ]
                }
            }
        )
    )
    return path


@pytest.fixture()
def settings_with_full_baseline(tmp_path: Path) -> Path:
    path = tmp_path / "settings.local.json"
    path.write_text(
        json.dumps(
            {
                "permissions": {
                    "allow": list(missing_linear_mcp_allow.EXPECTED_BASELINE_TOOLS),
                }
            }
        )
    )
    return path


@pytest.fixture()
def settings_without_linear(tmp_path: Path) -> Path:
    path = tmp_path / "settings.local.json"
    path.write_text(
        json.dumps(
            {
                "permissions": {
                    "allow": [
                        "Bash(gh pr view:*)",
                        "mcp__plugin_Dev10x_cli__mktmp",
                    ]
                }
            }
        )
    )
    return path


class TestMissingLinearMcpAllowDetect:
    def test_flags_partial_linear_usage(self, settings_with_partial_linear: Path) -> None:
        context = Context(settings_paths=(settings_with_partial_linear,))

        findings = missing_linear_mcp_allow.detect(context)

        assert len(findings) == 1
        assert findings[0].strategy_id == "missing-linear-mcp-allow"
        assert findings[0].severity == "drift"
        assert str(settings_with_partial_linear) == findings[0].location
        assert "missing_tools" in findings[0].metadata
        assert (
            len(findings[0].metadata["missing_tools"])
            >= missing_linear_mcp_allow.MISSING_THRESHOLD - 1
        )

    def test_silent_when_baseline_complete(self, settings_with_full_baseline: Path) -> None:
        context = Context(settings_paths=(settings_with_full_baseline,))

        findings = missing_linear_mcp_allow.detect(context)

        assert findings == []

    def test_silent_when_no_linear_usage(self, settings_without_linear: Path) -> None:
        context = Context(settings_paths=(settings_without_linear,))

        findings = missing_linear_mcp_allow.detect(context)

        assert findings == []

    def test_silent_when_settings_file_missing(self, tmp_path: Path) -> None:
        context = Context(settings_paths=(tmp_path / "absent.json",))

        findings = missing_linear_mcp_allow.detect(context)

        assert findings == []

    def test_handles_invalid_json(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.local.json"
        path.write_text("{not json}")
        context = Context(settings_paths=(path,))

        findings = missing_linear_mcp_allow.detect(context)

        assert findings == []

    def test_detects_linear_server_variant(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.local.json"
        path.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "mcp__linear-server__get_issue",
                            "mcp__linear-server__list_issues",
                        ]
                    }
                }
            )
        )
        context = Context(settings_paths=(path,))

        findings = missing_linear_mcp_allow.detect(context)

        assert len(findings) == 1


class TestMissingLinearMcpAllowRemediate:
    def test_proposes_delegating_to_upgrade_cleanup(
        self, settings_with_partial_linear: Path
    ) -> None:
        context = Context(settings_paths=(settings_with_partial_linear,))
        finding = missing_linear_mcp_allow.detect(context)[0]

        remediation = missing_linear_mcp_allow.remediate(finding)

        assert remediation.kind == "delegate_skill"
        assert remediation.target == "Dev10x:upgrade-cleanup"
        assert "missing_tools" in remediation.action
