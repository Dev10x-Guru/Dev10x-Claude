"""Tests for runtime MCP server discovery and capability_group support (GH-371)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.skills.permission.enumerate_mcp import (
    CapabilityGroupEntry,
    McpServerEntry,
    build_capability_groups,
    discover_all_mcp_servers,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def settings_with_three_sentry_servers(tmp_path: Path) -> Path:
    """Settings file with three Sentry MCP server variants (GH-271 #222)."""
    path = tmp_path / "settings.local.json"
    path.write_text(
        json.dumps(
            {
                "permissions": {
                    "allow": [
                        # claude.ai-hosted
                        "mcp__claude_ai_Sentry__search_issues",
                        "mcp__claude_ai_Sentry__get_issue",
                        # user-installed
                        "mcp__sentry__search_issues",
                        "mcp__sentry__get_issue",
                        # plugin-distributed
                        "mcp__plugin_sentry_sentry__search_issues",
                        "mcp__plugin_sentry_sentry__get_issue",
                        # unrelated
                        "Bash(git status:*)",
                        "mcp__plugin_Dev10x_cli__mktmp",
                    ]
                }
            }
        )
    )
    return path


@pytest.fixture()
def settings_with_single_server(tmp_path: Path) -> Path:
    """Settings file with only one MCP server — no duplicates."""
    path = tmp_path / "settings.local.json"
    path.write_text(
        json.dumps(
            {
                "permissions": {
                    "allow": [
                        "mcp__claude_ai_Linear__get_issue",
                        "mcp__claude_ai_Linear__list_issues",
                        "Bash(git log:*)",
                    ]
                }
            }
        )
    )
    return path


@pytest.fixture()
def empty_settings(tmp_path: Path) -> Path:
    """Settings file with no permissions block."""
    path = tmp_path / "settings.local.json"
    path.write_text(json.dumps({}))
    return path


# ---------------------------------------------------------------------------
# discover_all_mcp_servers
# ---------------------------------------------------------------------------


class TestDiscoverAllMcpServers:
    def test_discovers_all_three_sentry_sources(
        self, settings_with_three_sentry_servers: Path
    ) -> None:
        servers = discover_all_mcp_servers(settings_paths=[settings_with_three_sentry_servers])
        prefixes = {s.prefix for s in servers}

        assert "mcp__claude_ai_Sentry__" in prefixes
        assert "mcp__sentry__" in prefixes
        assert "mcp__plugin_sentry_sentry__" in prefixes

    def test_source_types_classified_correctly(
        self, settings_with_three_sentry_servers: Path
    ) -> None:
        servers = discover_all_mcp_servers(settings_paths=[settings_with_three_sentry_servers])
        by_prefix = {s.prefix: s for s in servers}

        assert by_prefix["mcp__claude_ai_Sentry__"].source_type == "claude_ai"
        assert by_prefix["mcp__sentry__"].source_type == "user_installed"
        assert by_prefix["mcp__plugin_sentry_sentry__"].source_type == "plugin"

    def test_service_name_extracted(self, settings_with_three_sentry_servers: Path) -> None:
        servers = discover_all_mcp_servers(settings_paths=[settings_with_three_sentry_servers])
        by_prefix = {s.prefix: s for s in servers}

        assert by_prefix["mcp__claude_ai_Sentry__"].service_name == "Sentry"
        assert by_prefix["mcp__sentry__"].service_name == "sentry"

    def test_non_mcp_rules_excluded(self, settings_with_three_sentry_servers: Path) -> None:
        servers = discover_all_mcp_servers(settings_paths=[settings_with_three_sentry_servers])
        for server in servers:
            assert "Bash" not in server.prefix

    def test_returns_empty_for_missing_file(self, tmp_path: Path) -> None:
        servers = discover_all_mcp_servers(settings_paths=[tmp_path / "nonexistent.json"])
        assert servers == []

    def test_returns_empty_for_malformed_json(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{not json}")
        servers = discover_all_mcp_servers(settings_paths=[path])
        assert servers == []

    def test_empty_permissions_returns_empty(self, empty_settings: Path) -> None:
        servers = discover_all_mcp_servers(settings_paths=[empty_settings])
        assert servers == []

    def test_tools_attached_to_server_entry(
        self, settings_with_three_sentry_servers: Path
    ) -> None:
        servers = discover_all_mcp_servers(settings_paths=[settings_with_three_sentry_servers])
        by_prefix = {s.prefix: s for s in servers}
        sentry_ai = by_prefix["mcp__claude_ai_Sentry__"]

        assert "mcp__claude_ai_Sentry__search_issues" in sentry_ai.tools
        assert "mcp__claude_ai_Sentry__get_issue" in sentry_ai.tools

    def test_deduplicates_across_settings_files(self, tmp_path: Path) -> None:
        """Same tool in two files yields one server entry."""
        path1 = tmp_path / "s1.json"
        path2 = tmp_path / "s2.json"
        tool = "mcp__sentry__search_issues"
        for p in (path1, path2):
            p.write_text(json.dumps({"permissions": {"allow": [tool]}}))

        servers = discover_all_mcp_servers(settings_paths=[path1, path2])
        sentry_entries = [s for s in servers if s.prefix == "mcp__sentry__"]
        assert len(sentry_entries) == 1

    def test_single_server_settings_has_correct_prefix(
        self, settings_with_single_server: Path
    ) -> None:
        servers = discover_all_mcp_servers(settings_paths=[settings_with_single_server])
        assert len(servers) == 1
        assert servers[0].prefix == "mcp__claude_ai_Linear__"


# ---------------------------------------------------------------------------
# build_capability_groups
# ---------------------------------------------------------------------------


class TestBuildCapabilityGroups:
    def test_groups_same_tool_name_across_prefixes(self) -> None:
        servers = [
            McpServerEntry(
                prefix="mcp__claude_ai_Sentry__",
                source_type="claude_ai",
                service_name="Sentry",
                tools=["mcp__claude_ai_Sentry__search_issues"],
            ),
            McpServerEntry(
                prefix="mcp__sentry__",
                source_type="user_installed",
                service_name="sentry",
                tools=["mcp__sentry__search_issues"],
            ),
        ]

        groups = build_capability_groups(servers)

        assert len(groups) == 1
        assert groups[0].tool_name == "search_issues"
        assert groups[0].capability_group == "search-issues"
        assert groups[0].server_count == 2

    def test_no_group_for_single_server(self) -> None:
        servers = [
            McpServerEntry(
                prefix="mcp__claude_ai_Linear__",
                source_type="claude_ai",
                service_name="Linear",
                tools=["mcp__claude_ai_Linear__get_issue"],
            )
        ]

        groups = build_capability_groups(servers)

        assert groups == []

    def test_three_servers_same_capability(self) -> None:
        servers = [
            McpServerEntry(
                prefix=f"mcp__sentry{i}__",
                source_type="user_installed",
                service_name=f"sentry{i}",
                tools=[f"mcp__sentry{i}__search_issues"],
            )
            for i in range(3)
        ]

        groups = build_capability_groups(servers)

        assert len(groups) == 1
        assert groups[0].server_count == 3

    def test_is_duplicate_reflects_server_count(self) -> None:
        single = CapabilityGroupEntry(
            capability_group="search-issues",
            tool_name="search_issues",
            entries=[("mcp__sentry__", "mcp__sentry__search_issues")],
        )
        multi = CapabilityGroupEntry(
            capability_group="search-issues",
            tool_name="search_issues",
            entries=[
                ("mcp__claude_ai_Sentry__", "mcp__claude_ai_Sentry__search_issues"),
                ("mcp__sentry__", "mcp__sentry__search_issues"),
            ],
        )

        assert not single.is_duplicate()
        assert multi.is_duplicate()

    def test_capability_group_slug_uses_hyphens(self) -> None:
        servers = [
            McpServerEntry(
                prefix=f"mcp__srv{i}__",
                source_type="user_installed",
                service_name=f"srv{i}",
                tools=[f"mcp__srv{i}__search_all_issues"],
            )
            for i in range(2)
        ]

        groups = build_capability_groups(servers)

        assert groups[0].capability_group == "search-all-issues"

    def test_distinct_tools_not_grouped(self) -> None:
        servers = [
            McpServerEntry(
                prefix="mcp__claude_ai_Sentry__",
                source_type="claude_ai",
                service_name="Sentry",
                tools=["mcp__claude_ai_Sentry__search_issues"],
            ),
            McpServerEntry(
                prefix="mcp__sentry__",
                source_type="user_installed",
                service_name="sentry",
                tools=["mcp__sentry__list_projects"],
            ),
        ]

        groups = build_capability_groups(servers)

        assert groups == []

    def test_mixed_overlapping_and_distinct_tools(self) -> None:
        servers = [
            McpServerEntry(
                prefix="mcp__claude_ai_Sentry__",
                source_type="claude_ai",
                service_name="Sentry",
                tools=[
                    "mcp__claude_ai_Sentry__search_issues",
                    "mcp__claude_ai_Sentry__unique_a",
                ],
            ),
            McpServerEntry(
                prefix="mcp__sentry__",
                source_type="user_installed",
                service_name="sentry",
                tools=[
                    "mcp__sentry__search_issues",
                    "mcp__sentry__unique_b",
                ],
            ),
        ]

        groups = build_capability_groups(servers)

        assert len(groups) == 1
        assert groups[0].tool_name == "search_issues"
