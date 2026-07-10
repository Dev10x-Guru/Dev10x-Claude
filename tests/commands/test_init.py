"""Tests for `dev10x init` guided setup (ADR-0018 relocation).

Durable prefs land in the global ``~/.config/Dev10x/friction.yaml`` (isolated
to a tmp home by the conftest fixture); the only per-project starter is the
work-on playbook. No per-repo ``config.yaml``/``session.yaml`` is written.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from dev10x.commands.init import _write_if_missing, init
from dev10x.domain.dev10x_paths import Dev10xConfigDir


def _playbook(root: Path) -> Path:
    return root / ".claude" / "Dev10x" / "playbooks" / "work-on.yaml"


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
        return CliRunner().invoke(init, ["--non-interactive", "--path", str(project)])

    def test_exits_successfully(self, result: object) -> None:
        assert result.exit_code == 0

    def test_creates_global_friction_yaml(self, result: object) -> None:
        assert Dev10xConfigDir.friction_yaml().exists()

    def test_friction_defaults_to_guided(self, result: object) -> None:
        assert "friction_level: guided" in Dev10xConfigDir.friction_yaml().read_text()

    def test_writes_nothing_durable_under_repo_claude(self, result: object, project: Path) -> None:
        dev10x_dir = project / ".claude" / "Dev10x"
        assert not (dev10x_dir / "config.yaml").exists()
        assert not (dev10x_dir / "session.yaml").exists()

    def test_creates_work_on_playbook(self, result: object, project: Path) -> None:
        assert _playbook(project).exists()

    def test_prints_quick_start_card(self, result: object) -> None:
        assert "Next 5 commands" in result.output
        assert "/Dev10x:git-commit" in result.output
        assert "/Dev10x:gh-pr-create" in result.output

    def test_prints_config_location(self, result: object, project: Path) -> None:
        assert str(project / ".claude" / "Dev10x") in result.output


class TestInitIdempotent:
    """Re-running without --setup does not overwrite an initialized project."""

    def test_preserves_existing_playbook(self, tmp_path: Path) -> None:
        playbook = _playbook(tmp_path)
        playbook.parent.mkdir(parents=True)
        playbook.write_text("overrides: [custom]\n")
        result = CliRunner().invoke(init, ["--non-interactive", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert playbook.read_text() == "overrides: [custom]\n"

    def test_skips_interactive_when_already_set_up(self, tmp_path: Path) -> None:
        playbook = _playbook(tmp_path)
        playbook.parent.mkdir(parents=True)
        playbook.write_text("overrides: []\n")
        result = CliRunner().invoke(init, ["--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "already present" in result.output


class TestInitInteractive:
    """Interactive mode collects friction level + solo-maintainer choice and
    writes them into the global friction.yaml."""

    def test_writes_user_choices(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            init,
            ["--path", str(tmp_path), "--setup"],
            input="adaptive\ny\n",
        )
        assert result.exit_code == 0
        friction = Dev10xConfigDir.friction_yaml().read_text()
        assert "friction_level: adaptive" in friction
        assert "solo-maintainer" in friction


class TestInitMissingPath:
    """Invalid --path should error."""

    def test_errors_on_nonexistent_path(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(init, ["--non-interactive", "--path", str(tmp_path / "nope")])
        assert result.exit_code != 0
