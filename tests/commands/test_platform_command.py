"""Tests for `dev10x platform` CLI glue (GH-1448).

`src/dev10x/commands/platform.py` had zero tests importing it or
`CliRunner`-invoking `add`/`list`/`remove`/`known` — including its
two live `sys.exit(1)` branches (unknown platform on add, not-found
on remove). The domain layer (`platform/registry.py`) is already
covered by `tests/platform/test_registry.py`; this covers the CLI
glue on top of it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from dev10x.commands.platform import platform


@pytest.fixture(autouse=True)
def _isolated_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point PlatformRepository()'s default path at a scratch file so
    the CLI tests never touch the real ~/.config/Dev10x/platforms.yaml.
    """
    registry_path = tmp_path / "platforms.yaml"
    monkeypatch.setattr("dev10x.platform.registry.REGISTRY_FILE", registry_path)
    return registry_path


class TestPlatformAdd:
    def test_registers_a_known_platform(self) -> None:
        result = CliRunner().invoke(platform, ["add", "windsurf"])

        assert result.exit_code == 0
        assert "Registered" in result.output
        assert "windsurf" in result.output

    def test_reports_config_paths(self) -> None:
        result = CliRunner().invoke(platform, ["add", "claude-code"])

        assert result.exit_code == 0
        assert "config:" in result.output
        assert "plugins:" in result.output
        assert "settings:" in result.output

    def test_unknown_platform_exits_one(self) -> None:
        result = CliRunner().invoke(platform, ["add", "not-a-real-platform"])

        assert result.exit_code == 1
        assert "Unknown platform" in result.output

    def test_unknown_platform_lists_known_names(self) -> None:
        result = CliRunner().invoke(platform, ["add", "not-a-real-platform"])

        assert "claude-code" in result.output

    def test_config_dir_override_is_expanded_and_resolved(self, tmp_path: Path) -> None:
        override = tmp_path / "custom-config"
        override.mkdir()
        result = CliRunner().invoke(platform, ["add", "cursor", "--config-dir", str(override)])

        assert result.exit_code == 0
        assert str(override) in result.output

    def test_playbook_override_reported_when_set(self) -> None:
        result = CliRunner().invoke(
            platform, ["add", "continue", "--playbook", "playbooks/continue.yaml"]
        )

        assert result.exit_code == 0
        assert "playbook:" in result.output
        assert "playbooks/continue.yaml" in result.output

    def test_playbook_line_omitted_when_unset(self) -> None:
        result = CliRunner().invoke(platform, ["add", "windsurf"])

        assert result.exit_code == 0
        assert "playbook:" not in result.output


class TestPlatformList:
    def test_empty_registry_prints_hint(self) -> None:
        result = CliRunner().invoke(platform, ["list"])

        assert result.exit_code == 0
        assert "No platforms registered" in result.output
        assert "dev10x platform add" in result.output

    def test_lists_registered_platforms(self) -> None:
        CliRunner().invoke(platform, ["add", "claude-code"])
        CliRunner().invoke(platform, ["add", "cursor"])

        result = CliRunner().invoke(platform, ["list"])

        assert result.exit_code == 0
        assert "claude-code" in result.output
        assert "cursor" in result.output

    def test_lists_playbook_override_when_set(self) -> None:
        CliRunner().invoke(platform, ["add", "continue", "--playbook", "playbooks/continue.yaml"])

        result = CliRunner().invoke(platform, ["list"])

        assert result.exit_code == 0
        assert "playbooks/continue.yaml" in result.output


class TestPlatformRemove:
    def test_removes_a_registered_platform(self) -> None:
        CliRunner().invoke(platform, ["add", "cursor"])

        result = CliRunner().invoke(platform, ["remove", "cursor"])

        assert result.exit_code == 0
        assert "Removed cursor" in result.output

        listing = CliRunner().invoke(platform, ["list"])
        assert "cursor" not in listing.output

    def test_not_found_exits_one(self) -> None:
        result = CliRunner().invoke(platform, ["remove", "cursor"])

        assert result.exit_code == 1
        assert "No registration found" in result.output


class TestPlatformKnown:
    def test_prints_the_builtin_catalog(self) -> None:
        result = CliRunner().invoke(platform, ["known"])

        assert result.exit_code == 0
        assert "claude-code" in result.output
        assert "Claude Code" in result.output
        assert "windsurf" in result.output

    def test_sorted_alphabetically(self) -> None:
        result = CliRunner().invoke(platform, ["known"])

        names = [line.split()[0] for line in result.output.splitlines() if line.strip()]
        assert names == sorted(names)
