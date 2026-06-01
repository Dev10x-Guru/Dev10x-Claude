"""Tests for the mcp-horizontal-duplicates doctor strategy (GH-371)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.skills.doctor.strategies import mcp_horizontal_duplicates
from dev10x.skills.doctor.strategy import Context


@pytest.fixture()
def settings_with_three_sentry_servers(tmp_path: Path) -> Path:
    """Three Sentry servers: claude_ai, user-installed, plugin-distributed."""
    path = tmp_path / "settings.local.json"
    path.write_text(
        json.dumps(
            {
                "permissions": {
                    "allow": [
                        "mcp__claude_ai_Sentry__search_issues",
                        "mcp__claude_ai_Sentry__get_issue",
                        "mcp__sentry__search_issues",
                        "mcp__sentry__get_issue",
                        "mcp__plugin_sentry_sentry__search_issues",
                        "Bash(git status:*)",
                    ]
                }
            }
        )
    )
    return path


@pytest.fixture()
def settings_with_single_server(tmp_path: Path) -> Path:
    """Only one Linear MCP server — no horizontal duplicates."""
    path = tmp_path / "settings.local.json"
    path.write_text(
        json.dumps(
            {
                "permissions": {
                    "allow": [
                        "mcp__claude_ai_Linear__get_issue",
                        "mcp__claude_ai_Linear__list_issues",
                    ]
                }
            }
        )
    )
    return path


@pytest.fixture()
def settings_empty(tmp_path: Path) -> Path:
    path = tmp_path / "settings.local.json"
    path.write_text(json.dumps({}))
    return path


class TestMcpHorizontalDuplicatesDetect:
    def test_finds_duplicates_across_three_sentry_servers(
        self, settings_with_three_sentry_servers: Path
    ) -> None:
        context = Context(settings_paths=(settings_with_three_sentry_servers,))

        findings = mcp_horizontal_duplicates.detect(context)

        assert len(findings) > 0
        strategy_ids = {f.strategy_id for f in findings}
        assert strategy_ids == {"mcp-horizontal-duplicates"}

    def test_finding_metadata_has_capability_group(
        self, settings_with_three_sentry_servers: Path
    ) -> None:
        context = Context(settings_paths=(settings_with_three_sentry_servers,))

        findings = mcp_horizontal_duplicates.detect(context)

        for f in findings:
            assert "capability_group" in f.metadata
            assert "server_count" in f.metadata
            assert f.metadata["server_count"] >= 2

    def test_finding_severity_is_suggestion(
        self, settings_with_three_sentry_servers: Path
    ) -> None:
        context = Context(settings_paths=(settings_with_three_sentry_servers,))

        findings = mcp_horizontal_duplicates.detect(context)

        for f in findings:
            assert f.severity == "suggestion"

    def test_silent_for_single_server(self, settings_with_single_server: Path) -> None:
        context = Context(settings_paths=(settings_with_single_server,))

        findings = mcp_horizontal_duplicates.detect(context)

        assert findings == []

    def test_silent_for_empty_settings(self, settings_empty: Path) -> None:
        context = Context(settings_paths=(settings_empty,))

        findings = mcp_horizontal_duplicates.detect(context)

        assert findings == []

    def test_silent_when_no_settings_file(self, tmp_path: Path) -> None:
        context = Context(settings_paths=(tmp_path / "absent.json",))

        findings = mcp_horizontal_duplicates.detect(context)

        assert findings == []

    def test_finding_evidence_names_all_prefixes(
        self, settings_with_three_sentry_servers: Path
    ) -> None:
        context = Context(settings_paths=(settings_with_three_sentry_servers,))

        findings = mcp_horizontal_duplicates.detect(context)

        evidence_combined = " ".join(f.evidence for f in findings)
        assert "mcp__claude_ai_Sentry__" in evidence_combined
        assert "mcp__sentry__" in evidence_combined

    def test_uses_context_settings_paths_over_default(self, tmp_path: Path) -> None:
        """When context has settings_paths, they are used exclusively."""
        path = tmp_path / "settings.local.json"
        path.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "mcp__claude_ai_Sentry__search_issues",
                            "mcp__sentry__search_issues",
                        ]
                    }
                }
            )
        )
        context = Context(settings_paths=(path,))

        findings = mcp_horizontal_duplicates.detect(context)

        assert len(findings) == 1

    def test_finding_entries_metadata_lists_prefix_and_tool(
        self, settings_with_three_sentry_servers: Path
    ) -> None:
        context = Context(settings_paths=(settings_with_three_sentry_servers,))

        findings = mcp_horizontal_duplicates.detect(context)

        for f in findings:
            entries = f.metadata.get("entries", [])
            assert len(entries) >= 2
            for entry in entries:
                assert "prefix" in entry
                assert "tool" in entry


class TestMcpHorizontalDuplicatesRemediate:
    def test_remediation_kind_is_file_issue(
        self, settings_with_three_sentry_servers: Path
    ) -> None:
        context = Context(settings_paths=(settings_with_three_sentry_servers,))
        finding = mcp_horizontal_duplicates.detect(context)[0]

        remediation = mcp_horizontal_duplicates.remediate(finding)

        assert remediation.kind == "file_issue"

    def test_remediation_includes_capability_group(
        self, settings_with_three_sentry_servers: Path
    ) -> None:
        context = Context(settings_paths=(settings_with_three_sentry_servers,))
        finding = mcp_horizontal_duplicates.detect(context)[0]

        remediation = mcp_horizontal_duplicates.remediate(finding)

        assert "capability_group" in remediation.action
        assert remediation.action["capability_group"] is not None

    def test_remediation_includes_server_count(
        self, settings_with_three_sentry_servers: Path
    ) -> None:
        context = Context(settings_paths=(settings_with_three_sentry_servers,))
        finding = mcp_horizontal_duplicates.detect(context)[0]

        remediation = mcp_horizontal_duplicates.remediate(finding)

        assert remediation.action.get("server_count", 0) >= 2


class TestMcpHorizontalDuplicatesStrategy:
    def test_strategy_has_correct_id(self) -> None:
        assert mcp_horizontal_duplicates.STRATEGY.id == "mcp-horizontal-duplicates"

    def test_strategy_is_callable(self) -> None:
        assert callable(mcp_horizontal_duplicates.STRATEGY.detect)
        assert callable(mcp_horizontal_duplicates.STRATEGY.remediate)

    def test_strategy_description_mentions_source_types(self) -> None:
        desc = mcp_horizontal_duplicates.STRATEGY.description
        assert "claude.ai" in desc or "claude_ai" in desc or "MCP" in desc
