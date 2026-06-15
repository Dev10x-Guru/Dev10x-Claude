"""Tests for `dev10x config` CLI commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from dev10x.commands.config import config


class TestConfigRoot:
    def test_prints_config_home(self) -> None:
        runner = CliRunner()
        with patch(
            "dev10x.commands.config.Dev10xConfigDir.home",
            return_value=Path("/fake/config/root"),
        ):
            result = runner.invoke(config, ["root"])
        assert result.exit_code == 0
        assert "/fake/config/root" in result.output


class TestConfigMigrate:
    def test_no_legacy_files(self) -> None:
        runner = CliRunner()
        with patch("dev10x.commands.config.stale_legacy_paths", return_value=[]):
            result = runner.invoke(config, ["migrate"])
        assert result.exit_code == 0
        assert "No legacy" in result.output

    def test_dry_run_lists_stale_paths(self) -> None:
        stale = [Path("/home/user/.claude/memory/Dev10x/foo.yaml")]
        runner = CliRunner()
        with patch("dev10x.commands.config.stale_legacy_paths", return_value=stale):
            result = runner.invoke(config, ["migrate", "--dry-run"])
        assert result.exit_code == 0
        assert "Would migrate 1 legacy entry" in result.output
        assert "foo.yaml" in result.output

    def test_dry_run_plural(self) -> None:
        stale = [Path("/a/one.yaml"), Path("/a/two.yaml")]
        runner = CliRunner()
        with patch("dev10x.commands.config.stale_legacy_paths", return_value=stale):
            result = runner.invoke(config, ["migrate", "--dry-run"])
        assert "2 legacy entries" in result.output

    def test_dry_run_does_not_call_migrate_all(self) -> None:
        stale = [Path("/home/user/.claude/memory/Dev10x/foo.yaml")]
        runner = CliRunner()
        with (
            patch("dev10x.commands.config.stale_legacy_paths", return_value=stale),
            patch("dev10x.commands.config.migrate_all") as mock_migrate,
        ):
            runner.invoke(config, ["migrate", "--dry-run"])
        mock_migrate.assert_not_called()

    def test_migrate_reports_moved_files(self) -> None:
        stale = [Path("/home/user/.claude/memory/Dev10x/foo.yaml")]
        migrated = [Path("/home/user/.config/Dev10x/foo.yaml")]
        runner = CliRunner()
        with (
            patch("dev10x.commands.config.stale_legacy_paths", return_value=stale),
            patch("dev10x.commands.config.migrate_all", return_value=migrated),
        ):
            result = runner.invoke(config, ["migrate"])
        assert result.exit_code == 0
        assert "Migrated 1 entry" in result.output
        assert "foo.yaml" in result.output

    def test_migrate_nothing_when_destination_populated(self) -> None:
        stale = [Path("/home/user/.claude/memory/Dev10x/foo.yaml")]
        runner = CliRunner()
        with (
            patch("dev10x.commands.config.stale_legacy_paths", return_value=stale),
            patch("dev10x.commands.config.migrate_all", return_value=[]),
        ):
            result = runner.invoke(config, ["migrate"])
        assert "Nothing to migrate" in result.output


class TestConfigDoctor:
    def test_clean_state(self) -> None:
        runner = CliRunner()
        with patch("dev10x.commands.config.stale_legacy_paths", return_value=[]):
            result = runner.invoke(config, ["doctor"])
        assert result.exit_code == 0
        assert "canonical XDG location" in result.output

    def test_lists_stale_paths(self) -> None:
        stale = [Path("/home/user/.claude/memory/Dev10x/foo.yaml")]
        runner = CliRunner()
        with patch("dev10x.commands.config.stale_legacy_paths", return_value=stale):
            result = runner.invoke(config, ["doctor"])
        assert result.exit_code == 0
        assert "1 legacy Dev10x config entry" in result.output
        assert "foo.yaml" in result.output

    def test_lists_multiple_stale_paths(self) -> None:
        stale = [Path("/a/one.yaml"), Path("/a/two.yaml")]
        runner = CliRunner()
        with patch("dev10x.commands.config.stale_legacy_paths", return_value=stale):
            result = runner.invoke(config, ["doctor"])
        assert "2 legacy Dev10x config entries" in result.output

    def test_suggests_migrate_command_when_stale(self) -> None:
        stale = [Path("/a/foo.yaml")]
        runner = CliRunner()
        with patch("dev10x.commands.config.stale_legacy_paths", return_value=stale):
            result = runner.invoke(config, ["doctor"])
        assert "dev10x config migrate" in result.output
