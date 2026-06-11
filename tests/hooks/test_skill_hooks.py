"""Tests for dev10x hook skill {tmpdir,metrics} and hook ruff-format."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from dev10x.cli import cli


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


class TestSkillTmpdir:
    def test_creates_skill_directory(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["hook", "skill", "tmpdir"],
            input=json.dumps({"tool_input": {"skill": "Dev10x:git-commit"}}),
        )

        assert result.exit_code == 0
        assert Path("/tmp/Dev10x/Dev10x-git-commit").exists()

    def test_sanitizes_colon_to_dash(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["hook", "skill", "tmpdir"],
            input=json.dumps({"tool_input": {"skill": "test:skill-name"}}),
        )

        assert result.exit_code == 0
        assert Path("/tmp/Dev10x/test-skill-name").exists()

    def test_exits_silently_without_skill(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["hook", "skill", "tmpdir"],
            input=json.dumps({"tool_input": {}}),
        )

        assert result.exit_code == 0
        assert result.output == ""

    def test_exits_silently_on_empty_skill(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["hook", "skill", "tmpdir"],
            input=json.dumps({}),
        )

        assert result.exit_code == 0
        assert result.output == ""


class TestSkillMetrics:
    def test_creates_metrics_file(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import dev10x.hooks.skill as mod

        monkeypatch.setattr(mod, "_get_toplevel", lambda: str(tmp_path))
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        result = runner.invoke(
            cli,
            ["hook", "skill", "metrics"],
            input=json.dumps(
                {
                    "tool_input": {"skill": "Dev10x:git-commit"},
                    "session_id": "sess-abc",
                }
            ),
        )

        assert result.exit_code == 0
        metrics_files = list((tmp_path / ".claude" / "projects" / "_metrics").glob("*.jsonl"))
        assert len(metrics_files) == 1

    def test_metrics_entry_schema(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import dev10x.hooks.skill as mod

        monkeypatch.setattr(mod, "_get_toplevel", lambda: str(tmp_path))
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        runner.invoke(
            cli,
            ["hook", "skill", "metrics"],
            input=json.dumps(
                {
                    "tool_input": {"skill": "Dev10x:review"},
                    "session_id": "sess-xyz",
                }
            ),
        )

        metrics_files = list((tmp_path / ".claude" / "projects" / "_metrics").glob("*.jsonl"))
        lines = metrics_files[0].read_text().strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["skill"] == "Dev10x:review"
        assert entry["session"] == "sess-xyz"
        assert "timestamp" in entry

    def test_appends_without_truncating_prior_entries(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # GH-548: the O_APPEND write must add to the file, never truncate
        # a prior concurrent writer's line.
        import dev10x.hooks.skill as mod

        monkeypatch.setattr(mod, "_get_toplevel", lambda: str(tmp_path))
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        payload = json.dumps(
            {"tool_input": {"skill": "Dev10x:git-commit"}, "session_id": "sess-1"}
        )
        runner.invoke(cli, ["hook", "skill", "metrics"], input=payload)
        runner.invoke(cli, ["hook", "skill", "metrics"], input=payload)

        metrics_files = list((tmp_path / ".claude" / "projects" / "_metrics").glob("*.jsonl"))
        lines = metrics_files[0].read_text().splitlines()
        assert len(lines) == 2
        assert all(json.loads(line)["skill"] == "Dev10x:git-commit" for line in lines)

    def test_exits_silently_without_skill(
        self,
        runner: CliRunner,
    ) -> None:
        result = runner.invoke(
            cli,
            ["hook", "skill", "metrics"],
            input=json.dumps({"session_id": "sess-abc"}),
        )

        assert result.exit_code == 0
        assert result.output == ""

    def test_exits_silently_without_session_id(
        self,
        runner: CliRunner,
    ) -> None:
        result = runner.invoke(
            cli,
            ["hook", "skill", "metrics"],
            input=json.dumps({"tool_input": {"skill": "Dev10x:git-commit"}}),
        )

        assert result.exit_code == 0
        assert result.output == ""

    def test_prunes_old_metrics_files(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import dev10x.hooks.skill as mod

        monkeypatch.setattr(mod, "_get_toplevel", lambda: str(tmp_path))
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        metrics_dir = tmp_path / ".claude" / "projects" / "_metrics"
        metrics_dir.mkdir(parents=True)

        old_file = metrics_dir / "old_2020-01-01.jsonl"
        old_file.write_text('{"skill": "old", "session": "x", "timestamp": "2020-01-01"}\n')
        import time

        old_mtime = time.time() - (31 * 24 * 3600)
        import os

        os.utime(old_file, (old_mtime, old_mtime))

        runner.invoke(
            cli,
            ["hook", "skill", "metrics"],
            input=json.dumps(
                {
                    "tool_input": {"skill": "Dev10x:git-commit"},
                    "session_id": "sess-prune",
                }
            ),
        )

        assert not old_file.exists()


class TestRuffFormat:
    def test_formats_python_file(
        self,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        py_file = tmp_path / "test_module.py"
        py_file.write_text("x=1\n")

        result = runner.invoke(
            cli,
            ["hook", "ruff-format"],
            input=json.dumps({"tool_input": {"file_path": str(py_file)}}),
        )

        assert result.exit_code == 0

    def test_exits_silently_for_non_python_file(
        self,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        txt_file = tmp_path / "notes.txt"
        txt_file.write_text("hello\n")

        result = runner.invoke(
            cli,
            ["hook", "ruff-format"],
            input=json.dumps({"tool_input": {"file_path": str(txt_file)}}),
        )

        assert result.exit_code == 0
        assert result.output == ""

    def test_exits_silently_for_missing_file(
        self,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        result = runner.invoke(
            cli,
            ["hook", "ruff-format"],
            input=json.dumps({"tool_input": {"file_path": str(tmp_path / "nonexistent.py")}}),
        )

        assert result.exit_code == 0
        assert result.output == ""

    def test_exits_silently_without_file_path(
        self,
        runner: CliRunner,
    ) -> None:
        result = runner.invoke(
            cli,
            ["hook", "ruff-format"],
            input=json.dumps({"tool_input": {}}),
        )

        assert result.exit_code == 0
        assert result.output == ""
