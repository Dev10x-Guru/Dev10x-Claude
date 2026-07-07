"""Tests for `dev10x init` guided setup."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from dev10x.commands.init import _write_if_missing, init


class TestWriteIfMissing:
    """GH-562: O_EXCL atomic claim replaces the check-then-write race."""

    def test_writes_when_absent(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "file.yaml"
        assert _write_if_missing(target, "hello") is True
        assert target.read_text() == "hello"

    def test_returns_false_and_preserves_existing(self, tmp_path: Path) -> None:
        target = tmp_path / "file.yaml"
        target.write_text("original")
        assert _write_if_missing(target, "replacement") is False
        assert target.read_text() == "original"


class TestInitNonInteractive:
    """--non-interactive mode writes starter config and prints card."""

    @pytest.fixture
    def project(self, tmp_path: Path) -> Path:
        return tmp_path

    @pytest.fixture
    def result(self, project: Path) -> object:
        runner = CliRunner()
        return runner.invoke(
            init,
            ["--non-interactive", "--path", str(project)],
        )

    def test_exits_successfully(self, result: object) -> None:
        assert result.exit_code == 0

    def test_creates_session_yaml(self, result: object, project: Path) -> None:
        assert (project / ".claude" / "Dev10x" / "session.yaml").exists()

    def test_creates_config_yaml(self, result: object, project: Path) -> None:
        assert (project / ".claude" / "Dev10x" / "config.yaml").exists()

    def test_config_yaml_defaults_to_guided(self, result: object, project: Path) -> None:
        content = (project / ".claude" / "Dev10x" / "config.yaml").read_text()
        assert "friction_level: guided" in content

    def test_session_stub_has_no_durable_keys(self, result: object, project: Path) -> None:
        content = (project / ".claude" / "Dev10x" / "session.yaml").read_text()
        assert "friction_level" not in content

    def test_creates_work_on_playbook(self, result: object, project: Path) -> None:
        assert (project / ".claude" / "Dev10x" / "playbooks" / "work-on.yaml").exists()

    def test_prints_quick_start_card(self, result: object) -> None:
        assert "Next 5 commands" in result.output
        assert "/Dev10x:git-commit" in result.output
        assert "/Dev10x:gh-pr-create" in result.output

    def test_prints_config_location(self, result: object, project: Path) -> None:
        assert str(project / ".claude" / "Dev10x") in result.output


class TestInitIdempotent:
    """Re-running without --setup does not overwrite existing files."""

    def test_preserves_existing_session_yaml(self, tmp_path: Path) -> None:
        session_file = tmp_path / ".claude" / "Dev10x" / "session.yaml"
        session_file.parent.mkdir(parents=True)
        session_file.write_text("friction_level: strict\nactive_modes: ['solo-maintainer']\n")

        runner = CliRunner()
        result = runner.invoke(
            init,
            ["--non-interactive", "--path", str(tmp_path)],
        )

        assert result.exit_code == 0
        assert "friction_level: strict" in session_file.read_text()

    def test_skips_interactive_when_already_set_up(self, tmp_path: Path) -> None:
        session_file = tmp_path / ".claude" / "Dev10x" / "session.yaml"
        session_file.parent.mkdir(parents=True)
        session_file.write_text("friction_level: strict\nactive_modes: []\n")

        runner = CliRunner()
        result = runner.invoke(init, ["--path", str(tmp_path)])

        assert result.exit_code == 0
        assert "already present" in result.output


class TestInitInteractive:
    """Interactive mode collects friction level and solo-maintainer choice."""

    def test_writes_user_choices(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            init,
            ["--path", str(tmp_path), "--setup"],
            input="adaptive\ny\n",
        )

        assert result.exit_code == 0
        config_yaml = (tmp_path / ".claude" / "Dev10x" / "config.yaml").read_text()
        assert "friction_level: adaptive" in config_yaml
        assert "solo-maintainer" in config_yaml


class TestInitMissingPath:
    """Invalid --path should error."""

    def test_errors_on_nonexistent_path(self, tmp_path: Path) -> None:
        runner = CliRunner()
        missing = tmp_path / "nope"
        result = runner.invoke(
            init,
            ["--non-interactive", "--path", str(missing)],
        )

        assert result.exit_code != 0
