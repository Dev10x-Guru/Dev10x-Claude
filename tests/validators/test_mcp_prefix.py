"""Tests for McpPrefixValidator (DX013)."""

from __future__ import annotations

import pytest

from dev10x.validators.mcp_prefix import McpPrefixValidator
from tests.fakers import BashHookInputFaker


def _make_input(*, command: str) -> BashHookInputFaker:
    return BashHookInputFaker.build(command=command)


@pytest.fixture()
def validator() -> McpPrefixValidator:
    return McpPrefixValidator()


@pytest.mark.parametrize(
    "command",
    [
        "mcp__plugin_Dev10x_cli__check_top_level_comments",
        "mcp__plugin_Dev10x_cli__check_top_level_comments pr_number=357",
        "mcp__plugin_Dev10x_cli__mktmp namespace=git prefix=msg ext=.txt",
        "mcp__plugin_Dev10x_db__query 'SELECT 1'",
        "FOO=bar mcp__plugin_Dev10x_cli__pr_get pr_number=1",
        "FOO=bar BAZ=qux mcp__plugin_Dev10x_cli__issue_get",
    ],
)
def test_blocks_mcp_tool_as_command(validator: McpPrefixValidator, command: str) -> None:
    result = validator.validate(inp=_make_input(command=command))
    assert result is not None
    assert "tool-call" in result.message
    assert ".claude/rules/mcp-tools.md" in result.message


@pytest.mark.parametrize(
    "command",
    [
        "grep mcp__plugin tests/",
        'echo "mcp__foo__bar"',
        "cat file_with_mcp__name",
        "ls /tmp/mcp__plugin_Dev10x_cli__mktmp.txt",
        "git commit -m 'mcp__plugin_Dev10x_cli__mktmp'",
        "FOO=bar grep mcp__plugin_Dev10x_cli__mktmp src/",
    ],
)
def test_allows_mcp_substring_in_args(validator: McpPrefixValidator, command: str) -> None:
    assert validator.validate(inp=_make_input(command=command)) is None


@pytest.mark.parametrize(
    "command",
    [
        'echo "unbalanced',
        "mcp__plugin_Dev10x_cli__mktmp 'unterminated",
    ],
)
def test_unbalanced_quotes_returns_none(validator: McpPrefixValidator, command: str) -> None:
    assert validator.validate(inp=_make_input(command=command)) is None


def test_empty_command_returns_none(validator: McpPrefixValidator) -> None:
    assert validator.validate(inp=_make_input(command="")) is None


def test_env_prefix_only_returns_none(validator: McpPrefixValidator) -> None:
    assert validator.validate(inp=_make_input(command="FOO=bar")) is None


def test_single_underscore_segment_not_matched(
    validator: McpPrefixValidator,
) -> None:
    assert validator.validate(inp=_make_input(command="mcp__onlyserver")) is None


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("mcp__plugin_Dev10x_cli__mktmp", True),
        ("grep mcp__plugin tests/", True),
        ("git status", False),
        ("ls -la", False),
    ],
)
def test_should_run_gates_on_marker(
    validator: McpPrefixValidator, command: str, expected: bool
) -> None:
    assert validator.should_run(inp=_make_input(command=command)) is expected
