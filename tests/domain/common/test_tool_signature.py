"""Tests for ToolSignature value object (GH-543)."""

from __future__ import annotations

import pytest

from dev10x.domain.common.tool_signature import ACTION_TYPE_BY_TOOL, ToolSignature


class TestStr:
    def test_bash_renders_command(self) -> None:
        sig = ToolSignature(tool="Bash", value="git status")
        assert str(sig) == "Bash(git status)"

    def test_write_renders_path(self) -> None:
        sig = ToolSignature(tool="Write", value="/tmp/foo.txt")
        assert str(sig) == "Write(/tmp/foo.txt)"

    def test_read_renders_path(self) -> None:
        sig = ToolSignature(tool="Read", value="/home/user/file.py")
        assert str(sig) == "Read(/home/user/file.py)"

    def test_edit_renders_path(self) -> None:
        sig = ToolSignature(tool="Edit", value="/src/main.py")
        assert str(sig) == "Edit(/src/main.py)"

    def test_mcp_returns_tool_name_only(self) -> None:
        sig = ToolSignature(tool="mcp__plugin_Dev10x_cli__detect_tracker", value="ignored")
        assert str(sig) == "mcp__plugin_Dev10x_cli__detect_tracker"

    def test_fallback_renders_empty_parens(self) -> None:
        sig = ToolSignature(tool="AskUserQuestion", value="")
        assert str(sig) == "AskUserQuestion()"


class TestBuild:
    def test_bash_uses_command(self) -> None:
        sig = ToolSignature.build(tool_name="Bash", command="git log --oneline")
        assert str(sig) == "Bash(git log --oneline)"

    def test_write_uses_file_path(self) -> None:
        sig = ToolSignature.build(tool_name="Write", file_path="/tmp/out.md")
        assert str(sig) == "Write(/tmp/out.md)"

    def test_read_uses_file_path(self) -> None:
        sig = ToolSignature.build(tool_name="Read", file_path="/etc/hosts")
        assert str(sig) == "Read(/etc/hosts)"

    def test_edit_uses_file_path(self) -> None:
        sig = ToolSignature.build(tool_name="Edit", file_path="/src/foo.py")
        assert str(sig) == "Edit(/src/foo.py)"

    def test_mcp_ignores_command_and_path(self) -> None:
        sig = ToolSignature.build(
            tool_name="mcp__plugin_Dev10x_cli__pr_get",
            command="ignored",
            file_path="also_ignored",
        )
        assert str(sig) == "mcp__plugin_Dev10x_cli__pr_get"

    def test_fallback_tool_gets_empty_value(self) -> None:
        sig = ToolSignature.build(tool_name="Glob")
        assert sig.tool == "Glob"
        assert sig.value == ""
        assert str(sig) == "Glob()"


class TestFromHookInput:
    def test_bash_returns_signature(self) -> None:
        raw = {"tool_name": "Bash", "tool_input": {"command": "ls -la"}}
        result = ToolSignature.from_hook_input(raw)
        assert result is not None
        assert str(result) == "Bash(ls -la)"

    def test_bash_missing_command_returns_none(self) -> None:
        raw = {"tool_name": "Bash", "tool_input": {}}
        assert ToolSignature.from_hook_input(raw) is None

    def test_bash_empty_command_returns_none(self) -> None:
        raw = {"tool_name": "Bash", "tool_input": {"command": ""}}
        assert ToolSignature.from_hook_input(raw) is None

    def test_write_returns_signature(self) -> None:
        raw = {"tool_name": "Write", "tool_input": {"file_path": "/tmp/x.txt"}}
        result = ToolSignature.from_hook_input(raw)
        assert result is not None
        assert str(result) == "Write(/tmp/x.txt)"

    def test_read_returns_signature(self) -> None:
        raw = {"tool_name": "Read", "tool_input": {"file_path": "/src/a.py"}}
        result = ToolSignature.from_hook_input(raw)
        assert result is not None
        assert str(result) == "Read(/src/a.py)"

    def test_edit_returns_signature(self) -> None:
        raw = {"tool_name": "Edit", "tool_input": {"file_path": "/src/b.py"}}
        result = ToolSignature.from_hook_input(raw)
        assert result is not None
        assert str(result) == "Edit(/src/b.py)"

    def test_path_tool_missing_file_path_returns_none(self) -> None:
        raw = {"tool_name": "Write", "tool_input": {}}
        assert ToolSignature.from_hook_input(raw) is None

    def test_mcp_returns_tool_name(self) -> None:
        raw = {
            "tool_name": "mcp__plugin_Dev10x_cli__issue_get",
            "tool_input": {},
        }
        result = ToolSignature.from_hook_input(raw)
        assert result is not None
        assert str(result) == "mcp__plugin_Dev10x_cli__issue_get"

    def test_fallback_tool_returns_empty_parens(self) -> None:
        raw = {"tool_name": "Glob", "tool_input": {}}
        result = ToolSignature.from_hook_input(raw)
        assert result is not None
        assert str(result) == "Glob()"

    def test_missing_tool_name_returns_none(self) -> None:
        raw = {"tool_input": {"command": "ls"}}
        assert ToolSignature.from_hook_input(raw) is None

    def test_empty_tool_name_returns_none(self) -> None:
        raw = {"tool_name": "", "tool_input": {"command": "ls"}}
        assert ToolSignature.from_hook_input(raw) is None


class TestSuggestRule:
    @pytest.mark.parametrize(
        "tool,value,expected",
        [
            # Bash: multi-word → take first word
            ("Bash", "git status --short", "Bash(git:*)"),
            # Bash: single word
            ("Bash", "ls", "Bash(ls:*)"),
            # Bash: no space → whole value
            ("Bash", "uv", "Bash(uv:*)"),
            # Write path tool
            ("Write", "/home/user/project/src/foo.py", "Write(/home/user/project/src/**)"),
            # Read path tool
            ("Read", "/etc/hosts", "Read(/etc/**)"),
            # Edit path tool
            ("Edit", "/tmp/bar.txt", "Edit(/tmp/**)"),
        ],
    )
    def test_suggest_rule(self, tool: str, value: str, expected: str) -> None:
        sig = ToolSignature(tool=tool, value=value)
        assert sig.suggest_rule() == expected

    def test_mcp_suggests_server_wildcard(self) -> None:
        sig = ToolSignature(tool="mcp__plugin_Dev10x_cli__detect_tracker", value="")
        assert sig.suggest_rule() == "mcp__plugin_Dev10x_cli__*"

    def test_mcp_single_segment_returns_wildcard(self) -> None:
        # "mcp__only".rfind("__") == 3 > 0, so prefix is "mcp", result is "mcp__*"
        sig = ToolSignature(tool="mcp__only", value="")
        assert sig.suggest_rule() == "mcp__*"

    def test_fallback_returns_signature_unchanged(self) -> None:
        sig = ToolSignature(tool="Glob", value="")
        assert sig.suggest_rule() == "Glob()"


class TestClassifyAction:
    @pytest.mark.parametrize(
        "tool,input_summary,expected",
        [
            ("Skill", "", "Skill"),
            ("Agent", "", "Agent"),
            ("TaskCreate", "", "Task"),
            ("TaskUpdate", "", "Task"),
            ("TaskList", "", "Task"),
            ("TaskGet", "", "Task"),
            ("AskUserQuestion", "", "Decision"),
            ("Write", "", "CodeChange"),
            ("Edit", "", "CodeChange"),
            ("Read", "", "Read"),
            ("Glob", "", "Search"),
            ("Grep", "", "Search"),
            ("WebFetch", "", "Web"),
            ("WebSearch", "", "Web"),
        ],
    )
    def test_known_tools_from_map(self, tool: str, input_summary: str, expected: str) -> None:
        sig = ToolSignature(tool=tool, value="")
        assert sig.classify_action(input_summary=input_summary) == expected

    @pytest.mark.parametrize(
        "input_summary,expected",
        [
            ("git commit -m 'fix'", "Git"),
            ("git push origin main", "Git"),
            ("gh pr create --title foo", "PR"),
            ("gh issue view 42", "Issue"),
            ("uv run pytest tests/", "Test"),
            ("ruff check src/", "Lint"),
            ("chmod +x script.sh", "Config"),
            ("something unrecognized", "Other"),
        ],
    )
    def test_bash_keyword_classification(self, input_summary: str, expected: str) -> None:
        sig = ToolSignature(tool="Bash", value="")
        assert sig.classify_action(input_summary=input_summary) == expected

    def test_unknown_tool_returns_other(self) -> None:
        sig = ToolSignature(tool="UnknownTool", value="")
        assert sig.classify_action() == "Other"

    def test_mcp_tool_not_in_map_returns_other(self) -> None:
        sig = ToolSignature(tool="mcp__plugin_Dev10x_cli__detect_tracker", value="")
        assert sig.classify_action() == "Other"


class TestActionTypeByTool:
    """Verify the exported dict matches the known shape callers depend on."""

    def test_contains_required_keys(self) -> None:
        required = {
            "Skill",
            "Agent",
            "TaskCreate",
            "TaskUpdate",
            "Write",
            "Edit",
            "Read",
            "Glob",
            "Grep",
        }
        assert required <= ACTION_TYPE_BY_TOOL.keys()

    def test_write_is_code_change(self) -> None:
        assert ACTION_TYPE_BY_TOOL["Write"] == "CodeChange"

    def test_read_is_read(self) -> None:
        assert ACTION_TYPE_BY_TOOL["Read"] == "Read"
