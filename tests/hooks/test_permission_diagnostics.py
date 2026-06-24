"""Tests for the permission diagnostics module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.hooks.permission_diagnostics import (
    DiagnosticResult,
    SettingsFile,
    SettingsRuleMatch,
    _matches_rule,
    _suggest_rule,
    diagnose,
    extract_tool_signature,
    format_diagnostic,
)


class TestExtractToolSignature:
    def test_bash_tool(self) -> None:
        raw = {"tool_name": "Bash", "tool_input": {"command": "git status"}}
        assert extract_tool_signature(raw=raw) == "Bash(git status)"

    def test_write_tool(self) -> None:
        raw = {"tool_name": "Write", "tool_input": {"file_path": "/tmp/Dev10x/test.txt"}}
        assert extract_tool_signature(raw=raw) == "Write(/tmp/Dev10x/test.txt)"

    def test_read_tool(self) -> None:
        raw = {"tool_name": "Read", "tool_input": {"file_path": "/home/user/file.py"}}
        assert extract_tool_signature(raw=raw) == "Read(/home/user/file.py)"

    def test_edit_tool(self) -> None:
        raw = {"tool_name": "Edit", "tool_input": {"file_path": "/src/app.py"}}
        assert extract_tool_signature(raw=raw) == "Edit(/src/app.py)"

    def test_mcp_tool(self) -> None:
        raw = {
            "tool_name": "mcp__plugin_Dev10x_cli__mktmp",
            "tool_input": {"namespace": "git"},
        }
        assert extract_tool_signature(raw=raw) == "mcp__plugin_Dev10x_cli__mktmp"

    def test_empty_tool_name(self) -> None:
        assert extract_tool_signature(raw={"tool_name": "", "tool_input": {}}) is None

    def test_missing_tool_name(self) -> None:
        assert extract_tool_signature(raw={}) is None

    def test_bash_empty_command(self) -> None:
        raw = {"tool_name": "Bash", "tool_input": {"command": ""}}
        assert extract_tool_signature(raw=raw) is None

    def test_write_empty_file_path(self) -> None:
        raw = {"tool_name": "Write", "tool_input": {"file_path": ""}}
        assert extract_tool_signature(raw=raw) is None

    def test_unknown_tool(self) -> None:
        raw = {"tool_name": "Glob", "tool_input": {"pattern": "*.py"}}
        assert extract_tool_signature(raw=raw) == "Glob()"


class TestMatchesRule:
    def test_bash_exact_prefix(self) -> None:
        assert _matches_rule(signature="Bash(git status)", rule="Bash(git status:*)")

    def test_bash_prefix_with_args(self) -> None:
        assert _matches_rule(
            signature="Bash(git push origin main)",
            rule="Bash(git push:*)",
        )

    def test_bash_no_match(self) -> None:
        assert not _matches_rule(
            signature="Bash(git push origin main)",
            rule="Bash(npm:*)",
        )

    def test_write_glob_match(self) -> None:
        assert _matches_rule(
            signature="Write(/tmp/Dev10x/gh-issue/test.md)",
            rule="Write(/tmp/Dev10x/**)",
        )

    def test_write_no_match(self) -> None:
        assert not _matches_rule(
            signature="Write(/home/user/secret.txt)",
            rule="Write(/tmp/Dev10x/**)",
        )

    def test_mcp_exact_match(self) -> None:
        assert _matches_rule(
            signature="mcp__plugin_Dev10x_cli__mktmp",
            rule="mcp__plugin_Dev10x_cli__mktmp",
        )

    def test_mcp_wildcard_match(self) -> None:
        assert _matches_rule(
            signature="mcp__plugin_Dev10x_cli__mktmp",
            rule="mcp__plugin_Dev10x_cli__*",
        )

    def test_mcp_wildcard_different_server(self) -> None:
        assert not _matches_rule(
            signature="mcp__plugin_Dev10x_db__query",
            rule="mcp__plugin_Dev10x_cli__*",
        )

    def test_different_tool_types(self) -> None:
        assert not _matches_rule(
            signature="Write(/tmp/test)",
            rule="Read(/tmp/test)",
        )

    def test_rule_without_parens(self) -> None:
        assert _matches_rule(
            signature="mcp__plugin_Dev10x_cli__mktmp",
            rule="mcp__plugin_Dev10x_*",
        )

    def test_non_mcp_rule_without_parens(self) -> None:
        assert _matches_rule(
            signature="Bash(git status)",
            rule="Bash*",
        )

    def test_signature_without_parens_against_paren_rule(self) -> None:
        assert not _matches_rule(
            signature="WebSearch",
            rule="Bash(git:*)",
        )


class TestSuggestRule:
    def test_mcp_tool_suggests_server_wildcard(self) -> None:
        assert (
            _suggest_rule(signature="mcp__plugin_Dev10x_cli__mktmp") == "mcp__plugin_Dev10x_cli__*"
        )

    def test_bash_command_suggests_prefix_wildcard(self) -> None:
        assert _suggest_rule(signature="Bash(git status)") == "Bash(git:*)"

    def test_bash_single_word(self) -> None:
        assert _suggest_rule(signature="Bash(pytest)") == "Bash(pytest:*)"

    def test_write_suggests_parent_glob(self) -> None:
        result = _suggest_rule(signature="Write(/tmp/Dev10x/gh-issue/test.md)")
        assert result == "Write(/tmp/Dev10x/gh-issue/**)"

    def test_read_suggests_parent_glob(self) -> None:
        result = _suggest_rule(signature="Read(/home/user/project/src/main.py)")
        assert result == "Read(/home/user/project/src/**)"

    def test_mcp_short_name(self) -> None:
        assert _suggest_rule(signature="mcp__short") == "mcp__*"

    def test_unknown_tool_returns_signature(self) -> None:
        assert _suggest_rule(signature="Glob()") == "Glob()"

    def test_no_parens_returns_signature(self) -> None:
        assert _suggest_rule(signature="WebSearch") == "WebSearch"


class TestDiagnose:
    @pytest.fixture()
    def settings_dir(self, tmp_path: Path) -> Path:
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        return claude_dir

    @pytest.fixture()
    def user_settings_dir(self, tmp_path: Path) -> Path:
        user_claude = tmp_path / "user_home" / ".claude"
        user_claude.mkdir(parents=True)
        return user_claude

    @pytest.fixture()
    def write_raw(self) -> dict:
        return {
            "tool_name": "Write",
            "tool_input": {"file_path": "/tmp/Dev10x/gh-issue/review.md"},
        }

    @pytest.fixture()
    def mcp_raw(self) -> dict:
        return {
            "tool_name": "mcp__plugin_Dev10x_cli__mktmp",
            "tool_input": {"namespace": "git"},
        }

    def test_returns_none_for_empty_input(self, tmp_path: Path) -> None:
        assert diagnose(raw={}, cwd=str(tmp_path)) is None

    def test_no_settings_files_exist(
        self,
        tmp_path: Path,
        write_raw: dict,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "dev10x.hooks.permission_diagnostics.SETTINGS_PRECEDENCE",
            [
                SettingsFile(
                    label="project local",
                    path=Path(".claude/settings.local.json"),
                    precedence=3,
                ),
            ],
        )
        result = diagnose(raw=write_raw, cwd=str(tmp_path))
        assert result is not None
        assert "No matching allow rule found" in result.diagnosis

    def test_rule_in_user_settings_shadowed_by_project_local(
        self,
        tmp_path: Path,
        settings_dir: Path,
        write_raw: dict,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_local = settings_dir / "settings.local.json"
        project_local.write_text(json.dumps({"permissions": {"allow": ["Bash(git:*)"]}}))

        user_claude = tmp_path / "user_home" / ".claude"
        user_claude.mkdir(parents=True)
        user_settings = user_claude / "settings.json"
        user_settings.write_text(json.dumps({"permissions": {"allow": ["Write(/tmp/Dev10x/**)"]}}))

        monkeypatch.setattr(
            "dev10x.hooks.permission_diagnostics.SETTINGS_PRECEDENCE",
            [
                SettingsFile(
                    label="project local",
                    path=Path(".claude/settings.local.json"),
                    precedence=3,
                ),
                SettingsFile(
                    label="user settings",
                    path=user_settings,
                    precedence=5,
                ),
            ],
        )

        result = diagnose(raw=write_raw, cwd=str(tmp_path))
        assert result is not None
        assert "overrides" in result.diagnosis or "replacement" in result.diagnosis
        assert result.matches[0].has_allow_list is True
        assert result.matches[0].matching_rule is None
        assert result.matches[1].matching_rule == "Write(/tmp/Dev10x/**)"

    def test_rule_matched_in_project_local(
        self,
        tmp_path: Path,
        settings_dir: Path,
        write_raw: dict,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_local = settings_dir / "settings.local.json"
        project_local.write_text(json.dumps({"permissions": {"allow": ["Write(/tmp/Dev10x/**)"]}}))

        monkeypatch.setattr(
            "dev10x.hooks.permission_diagnostics.SETTINGS_PRECEDENCE",
            [
                SettingsFile(
                    label="project local",
                    path=Path(".claude/settings.local.json"),
                    precedence=3,
                ),
            ],
        )

        result = diagnose(raw=write_raw, cwd=str(tmp_path))
        assert result is not None
        assert result.matches[0].matching_rule == "Write(/tmp/Dev10x/**)"

    def test_mcp_wildcard_matching(
        self,
        tmp_path: Path,
        settings_dir: Path,
        mcp_raw: dict,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_local = settings_dir / "settings.local.json"
        project_local.write_text(
            json.dumps({"permissions": {"allow": ["mcp__plugin_Dev10x_cli__*"]}})
        )

        monkeypatch.setattr(
            "dev10x.hooks.permission_diagnostics.SETTINGS_PRECEDENCE",
            [
                SettingsFile(
                    label="project local",
                    path=Path(".claude/settings.local.json"),
                    precedence=3,
                ),
            ],
        )

        result = diagnose(raw=mcp_raw, cwd=str(tmp_path))
        assert result is not None
        assert result.matches[0].matching_rule == "mcp__plugin_Dev10x_cli__*"

    def test_fix_suggestion_when_shadowed(
        self,
        tmp_path: Path,
        settings_dir: Path,
        write_raw: dict,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_local = settings_dir / "settings.local.json"
        project_local.write_text(json.dumps({"permissions": {"allow": ["Bash(git:*)"]}}))

        user_claude = tmp_path / "user_home" / ".claude"
        user_claude.mkdir(parents=True)
        user_settings = user_claude / "settings.json"
        user_settings.write_text(json.dumps({"permissions": {"allow": ["Write(/tmp/Dev10x/**)"]}}))

        monkeypatch.setattr(
            "dev10x.hooks.permission_diagnostics.SETTINGS_PRECEDENCE",
            [
                SettingsFile(
                    label="project local",
                    path=Path(".claude/settings.local.json"),
                    precedence=3,
                ),
                SettingsFile(
                    label="user settings",
                    path=user_settings,
                    precedence=5,
                ),
            ],
        )

        result = diagnose(raw=write_raw, cwd=str(tmp_path))
        assert result is not None
        assert "Write(/tmp/Dev10x/**)" in result.fix_suggestion
        assert "project local" in result.fix_suggestion

    def test_fix_suggestion_when_no_rules_anywhere(
        self,
        tmp_path: Path,
        write_raw: dict,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "dev10x.hooks.permission_diagnostics.SETTINGS_PRECEDENCE",
            [],
        )

        result = diagnose(raw=write_raw, cwd=str(tmp_path))
        assert result is not None
        assert "Add an allow rule" in result.fix_suggestion

    def test_malformed_settings_file(
        self,
        tmp_path: Path,
        settings_dir: Path,
        write_raw: dict,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_local = settings_dir / "settings.local.json"
        project_local.write_text("not valid json {{{")

        monkeypatch.setattr(
            "dev10x.hooks.permission_diagnostics.SETTINGS_PRECEDENCE",
            [
                SettingsFile(
                    label="project local",
                    path=Path(".claude/settings.local.json"),
                    precedence=3,
                ),
            ],
        )

        result = diagnose(raw=write_raw, cwd=str(tmp_path))
        assert result is not None
        assert result.matches[0].has_allow_list is False

    def test_settings_with_allow_null(
        self,
        tmp_path: Path,
        settings_dir: Path,
        write_raw: dict,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_local = settings_dir / "settings.local.json"
        project_local.write_text(json.dumps({"permissions": {"allow": None}}))

        monkeypatch.setattr(
            "dev10x.hooks.permission_diagnostics.SETTINGS_PRECEDENCE",
            [
                SettingsFile(
                    label="project local",
                    path=Path(".claude/settings.local.json"),
                    precedence=3,
                ),
            ],
        )

        result = diagnose(raw=write_raw, cwd=str(tmp_path))
        assert result is not None
        assert result.matches[0].has_allow_list is False

    def test_settings_with_allow_not_a_list(
        self,
        tmp_path: Path,
        settings_dir: Path,
        write_raw: dict,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_local = settings_dir / "settings.local.json"
        project_local.write_text(json.dumps({"permissions": {"allow": "Bash(git:*)"}}))

        monkeypatch.setattr(
            "dev10x.hooks.permission_diagnostics.SETTINGS_PRECEDENCE",
            [
                SettingsFile(
                    label="project local",
                    path=Path(".claude/settings.local.json"),
                    precedence=3,
                ),
            ],
        )

        result = diagnose(raw=write_raw, cwd=str(tmp_path))
        assert result is not None
        assert result.matches[0].has_allow_list is False

    def test_fix_suggestion_when_no_match_but_winning_file(
        self,
        tmp_path: Path,
        settings_dir: Path,
        write_raw: dict,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_local = settings_dir / "settings.local.json"
        project_local.write_text(json.dumps({"permissions": {"allow": ["Bash(git:*)"]}}))

        monkeypatch.setattr(
            "dev10x.hooks.permission_diagnostics.SETTINGS_PRECEDENCE",
            [
                SettingsFile(
                    label="project local",
                    path=Path(".claude/settings.local.json"),
                    precedence=3,
                ),
            ],
        )

        result = diagnose(raw=write_raw, cwd=str(tmp_path))
        assert result is not None
        assert "Add" in result.fix_suggestion
        assert "project local" in result.fix_suggestion

    def test_defaults_cwd_when_empty(
        self,
        write_raw: dict,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "dev10x.hooks.permission_diagnostics.SETTINGS_PRECEDENCE",
            [],
        )
        result = diagnose(raw=write_raw, cwd="")
        assert result is not None


class TestFormatDiagnostic:
    @pytest.fixture()
    def shadowed_result(self) -> DiagnosticResult:
        project_local = SettingsFile(
            label="project local",
            path=Path(".claude/settings.local.json"),
            precedence=3,
        )
        user_settings = SettingsFile(
            label="user settings",
            path=Path("/home/testuser/.claude/settings.json"),
            precedence=5,
        )
        return DiagnosticResult(
            tool_signature="Write(/tmp/Dev10x/gh-issue/review.md)",
            matches=[
                SettingsRuleMatch(
                    settings_file=project_local,
                    matching_rule=None,
                    has_allow_list=True,
                ),
                SettingsRuleMatch(
                    settings_file=user_settings,
                    matching_rule="Write(/tmp/Dev10x/**)",
                    has_allow_list=True,
                ),
            ],
            diagnosis=(
                "project local defines its own permissions.allow list "
                "which overrides lower-precedence files."
            ),
            fix_suggestion="Add `Write(/tmp/Dev10x/**)` to project local",
        )

    def test_contains_tool_signature(self, shadowed_result: DiagnosticResult) -> None:
        output = format_diagnostic(result=shadowed_result)
        assert "Write(/tmp/Dev10x/gh-issue/review.md)" in output

    def test_shows_match_status(self, shadowed_result: DiagnosticResult) -> None:
        output = format_diagnostic(result=shadowed_result)
        assert "MATCH" in output
        assert "NOT COVERED" in output

    def test_shows_diagnosis(self, shadowed_result: DiagnosticResult) -> None:
        output = format_diagnostic(result=shadowed_result)
        assert "Diagnosis:" in output
        assert "overrides" in output

    def test_shows_fix_suggestion(self, shadowed_result: DiagnosticResult) -> None:
        output = format_diagnostic(result=shadowed_result)
        assert "Fix:" in output

    def test_no_fix_line_when_empty(self) -> None:
        result = DiagnosticResult(
            tool_signature="Bash(git status)",
            matches=[],
            diagnosis="test",
            fix_suggestion="",
        )
        output = format_diagnostic(result=result)
        assert "Fix:" not in output

    def test_no_allow_list_shown(self) -> None:
        sf = SettingsFile(label="project shared", path=Path("x"), precedence=4)
        result = DiagnosticResult(
            tool_signature="Bash(git status)",
            matches=[
                SettingsRuleMatch(settings_file=sf, matching_rule=None, has_allow_list=False),
            ],
            diagnosis="No matching allow rule found in any settings file.",
            fix_suggestion="",
        )
        output = format_diagnostic(result=result)
        assert "(no permissions.allow)" in output
