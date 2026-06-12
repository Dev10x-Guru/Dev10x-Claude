from __future__ import annotations

import pytest

from dev10x.domain.common.mcp_tool_name import (
    MCP_PREFIX,
    TOOL_NAME_PATTERN,
    WILDCARD_PATTERN,
    McpToolName,
)


class TestParse:
    @pytest.mark.parametrize(
        "raw,server,tool",
        [
            ("mcp__plugin_Dev10x_cli__detect_tracker", "plugin_Dev10x_cli", "detect_tracker"),
            ("mcp__claude_ai_Sentry__search_issues", "claude_ai_Sentry", "search_issues"),
            ("mcp__sentry__get_issue", "sentry", "get_issue"),
        ],
    )
    def test_parses_server_and_tool(self, raw: str, server: str, tool: str) -> None:
        name = McpToolName.parse(raw)

        assert name.server == server
        assert name.tool == tool
        assert str(name) == raw
        assert name.prefix == f"mcp__{server}__"

    @pytest.mark.parametrize(
        "raw",
        ["", "mcp__", "mcp__server", "Bash(ls)", "mcp__server__", "mcp__plugin_Dev10x_*"],
    )
    def test_rejects_invalid_forms(self, raw: str) -> None:
        with pytest.raises(ValueError):
            McpToolName.parse(raw)

    def test_rejects_non_string(self) -> None:
        with pytest.raises(ValueError):
            McpToolName.parse(None)  # type: ignore[arg-type]


class TestTryParse:
    def test_returns_name_on_success(self) -> None:
        assert McpToolName.try_parse("mcp__x__y") == McpToolName(server="x", tool="y")

    def test_returns_none_on_failure(self) -> None:
        assert McpToolName.try_parse("not-mcp") is None


class TestIsMcp:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("mcp__plugin_Dev10x_cli__mktmp", True),
            ("mcp__anything", True),
            ("Bash(grep mcp__ tests/)", False),
            ("", False),
        ],
    )
    def test_loose_sentinel(self, value: str, expected: bool) -> None:
        assert McpToolName.is_mcp(value) is expected


class TestIsCommandToken:
    def test_matches_full_tool_at_start(self) -> None:
        assert McpToolName.is_command_token("mcp__plugin_Dev10x_cli__pr_get pr_number=357")

    @pytest.mark.parametrize(
        "value",
        ["mcp__server", "grep mcp__ tests/", "mcp__only_server_part"],
    )
    def test_rejects_partial_or_embedded(self, value: str) -> None:
        assert McpToolName.is_command_token(value) is False


class TestIsWildcard:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("mcp__plugin_Dev10x_*", True),
            ("mcp__claude_ai_Sentry__*", True),
            ("mcp__plugin_Dev10x_cli__detect_tracker", False),
            ("mcp__plugin_Dev10x_* extra", False),
        ],
    )
    def test_glob_shape(self, value: str, expected: bool) -> None:
        assert McpToolName.is_wildcard(value) is expected


class TestPrefixOf:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("mcp__claude_ai_Sentry__search_issues", "mcp__claude_ai_Sentry__"),
            ("mcp__sentry__get_issue", "mcp__sentry__"),
            ("mcp__claude_ai_Sentry__*", "mcp__claude_ai_Sentry__"),
            ("mcp__too_short", None),
        ],
    )
    def test_structural_prefix(self, value: str, expected: str | None) -> None:
        assert McpToolName.prefix_of(value) == expected


def test_patterns_exposed_as_strings() -> None:
    assert MCP_PREFIX == "mcp__"
    assert TOOL_NAME_PATTERN == r"mcp__[A-Za-z0-9_]+__[A-Za-z0-9_]+"
    assert WILDCARD_PATTERN == r"mcp__[A-Za-z0-9_]+\*"
