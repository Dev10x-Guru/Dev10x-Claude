"""Tests for dev10x hook session {persist,goodbye}."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from dev10x.cli import cli


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


class TestSessionPersist:
    def test_creates_state_file(self, runner: CliRunner, tmp_path: Path) -> None:
        import dev10x.hooks.session as mod

        def fake_toplevel() -> str:
            return str(tmp_path / "myproject")

        (tmp_path / "myproject").mkdir(parents=True)

        def fake_home() -> Path:
            return tmp_path

        import unittest.mock as mock

        with mock.patch.object(mod, "_get_toplevel", fake_toplevel):
            with mock.patch.object(Path, "home", staticmethod(fake_home)):
                result = runner.invoke(
                    cli,
                    ["hook", "session", "persist"],
                    input=json.dumps({"session_id": "sess-abc-123"}),
                )

        assert result.exit_code == 0
        state_files = list((tmp_path / ".claude" / "projects" / "_session_state").glob("*.json"))
        assert len(state_files) == 1

    def test_state_file_schema(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import dev10x.hooks.session as mod

        project_dir = tmp_path / "myproject"
        project_dir.mkdir(parents=True)

        monkeypatch.setattr(mod, "_get_toplevel", lambda: str(project_dir))
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setattr(mod, "_run_git", lambda *a: "")

        result = runner.invoke(
            cli,
            ["hook", "session", "persist"],
            input=json.dumps({"session_id": "sess-xyz-999"}),
        )

        assert result.exit_code == 0
        state_files = list((tmp_path / ".claude" / "projects" / "_session_state").glob("*.json"))
        assert len(state_files) == 1
        state = json.loads(state_files[0].read_text())

        assert state["session_id"] == "sess-xyz-999"
        assert "branch" in state
        assert "worktree" in state
        assert "working_directory" in state
        assert "timestamp" in state
        assert "modified_files" in state
        assert "staged_files" in state
        assert "recent_commits" in state
        assert "has_plan" in state

    def test_exits_silently_without_session_id(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["hook", "session", "persist"],
            input=json.dumps({}),
        )

        assert result.exit_code == 0
        assert result.output == ""

    def test_exits_silently_on_invalid_json(self) -> None:
        from dev10x.hooks.session import session_persist

        original_stdin = sys.stdin
        sys.stdin = io.StringIO("{not valid json}")
        try:
            with pytest.raises(SystemExit) as exc_info:
                session_persist()
        finally:
            sys.stdin = original_stdin

        assert exc_info.value.code == 0

    def test_state_dir_permissions(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import dev10x.hooks.session as mod

        project_dir = tmp_path / "myproject"
        project_dir.mkdir(parents=True)

        monkeypatch.setattr(mod, "_get_toplevel", lambda: str(project_dir))
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setattr(mod, "_run_git", lambda *a: "")

        runner.invoke(
            cli,
            ["hook", "session", "persist"],
            input=json.dumps({"session_id": "sess-perms-test"}),
        )

        state_dir = tmp_path / ".claude" / "projects" / "_session_state"
        assert state_dir.exists()
        assert state_dir.stat().st_mode & 0o777 == 0o700


class TestSessionGoodbye:
    def test_outputs_community_url(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["hook", "session", "goodbye"],
            input=json.dumps({}),
        )

        assert result.exit_code == 0
        assert "Dev10x" in result.output
        assert "skool.com" in result.output

    def test_includes_resume_command_with_session_id(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["hook", "session", "goodbye"],
            input=json.dumps({"session_id": "my-session-id"}),
        )

        assert result.exit_code == 0
        assert "claude --resume my-session-id" in result.output

    def test_no_resume_command_without_session_id(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["hook", "session", "goodbye"],
            input=json.dumps({}),
        )

        assert result.exit_code == 0
        assert "claude --resume" not in result.output

    def test_handles_invalid_json_gracefully(self) -> None:
        from dev10x.hooks.session import session_goodbye

        captured = io.StringIO()
        original_stdin = sys.stdin
        sys.stdin = io.StringIO("{not valid json}")
        original_stdout = sys.stdout
        sys.stdout = captured
        try:
            session_goodbye()
        finally:
            sys.stdin = original_stdin
            sys.stdout = original_stdout

        output = captured.getvalue()
        assert "Dev10x" in output
        assert "claude --resume" not in output

    def test_outputs_ansi_hyperlink(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["hook", "session", "goodbye"],
            input=json.dumps({}),
        )

        assert result.exit_code == 0
        assert "\033]8;;" in result.output
