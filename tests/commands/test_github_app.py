"""Tests for `dev10x github-app` setup wizard."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from dev10x.commands import github_app as gha


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(gha, "CONFIG_DIR", tmp_path / "github-bot")
    monkeypatch.setattr(gha, "CONFIG_PATH", tmp_path / "github-bot" / "github-app.yaml")
    monkeypatch.setattr(gha, "KEY_PATH", tmp_path / "github-bot" / "dev10x-bot.pem")
    return tmp_path


class TestSetupWritesConfig:
    @pytest.fixture
    def fake_key(self) -> str:
        return "-----BEGIN RSA PRIVATE KEY-----\nFAKEKEY\n-----END RSA PRIVATE KEY-----\n"

    @pytest.fixture
    def stdin_input(self, fake_key: str) -> str:
        return "\n".join(["", "12345", "67890", *fake_key.splitlines(), ""]) + "\n"

    @pytest.fixture
    def result(
        self,
        fake_home: Path,
        stdin_input: str,
    ) -> object:
        runner = CliRunner()
        with patch.object(gha, "_validate_key_locally", return_value=None):
            return runner.invoke(gha.github_app, ["setup"], input=stdin_input)

    def test_exits_successfully(self, result: object) -> None:
        assert result.exit_code == 0, result.output

    def test_writes_config_file(self, result: object, fake_home: Path) -> None:
        assert (fake_home / "github-bot" / "github-app.yaml").is_file()

    def test_writes_key_file(self, result: object, fake_home: Path) -> None:
        assert (fake_home / "github-bot" / "dev10x-bot.pem").is_file()

    def test_config_contains_app_id(self, result: object, fake_home: Path) -> None:
        config = (fake_home / "github-bot" / "github-app.yaml").read_text()
        assert 'app_id: "12345"' in config

    def test_config_contains_installation_id(
        self,
        result: object,
        fake_home: Path,
    ) -> None:
        config = (fake_home / "github-bot" / "github-app.yaml").read_text()
        assert 'installation_id: "67890"' in config

    def test_key_file_has_600_perms(self, result: object, fake_home: Path) -> None:
        key_path = fake_home / "github-bot" / "dev10x-bot.pem"
        mode = stat.S_IMODE(key_path.stat().st_mode)
        assert mode == 0o600

    def test_config_file_has_600_perms(self, result: object, fake_home: Path) -> None:
        config_path = fake_home / "github-bot" / "github-app.yaml"
        mode = stat.S_IMODE(config_path.stat().st_mode)
        assert mode == 0o600


class TestSetupValidationFailure:
    def test_aborts_when_key_invalid(self, fake_home: Path) -> None:
        runner = CliRunner()
        stdin_input = (
            "\n12345\n\n-----BEGIN RSA PRIVATE KEY-----\nBADKEY\n-----END RSA PRIVATE KEY-----\n\n"
        )
        with patch.object(gha, "_validate_key_locally", return_value="bad signature"):
            result = runner.invoke(gha.github_app, ["setup"], input=stdin_input)

        assert result.exit_code == 1
        assert "bad signature" in result.output
        assert not (fake_home / "github-bot" / "github-app.yaml").exists()


class TestSetupOptionalInstallationId:
    def test_omits_installation_id_when_blank(self, fake_home: Path) -> None:
        runner = CliRunner()
        fake_key = "-----BEGIN RSA PRIVATE KEY-----\nKEY\n-----END RSA PRIVATE KEY-----\n"
        stdin_input = "\n".join(["", "12345", "", *fake_key.splitlines(), ""]) + "\n"
        with patch.object(gha, "_validate_key_locally", return_value=None):
            result = runner.invoke(gha.github_app, ["setup"], input=stdin_input)

        assert result.exit_code == 0, result.output
        config = (fake_home / "github-bot" / "github-app.yaml").read_text()
        assert "  installation_id:" not in config


class TestSetupRejectsExistingWithoutForce:
    def test_aborts_when_config_exists_and_no_confirm(
        self,
        fake_home: Path,
    ) -> None:
        gha.CONFIG_DIR.mkdir(parents=True)
        gha.CONFIG_PATH.write_text("github_app:\n  app_id: '0'\n")

        runner = CliRunner()
        result = runner.invoke(gha.github_app, ["setup"], input="\nN\n")

        assert result.exit_code == 1


class TestStatus:
    def test_reports_missing_config(self, fake_home: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(gha.github_app, ["status"])

        assert result.exit_code == 1
        assert "No config" in result.output

    def test_reports_present_config(self, fake_home: Path) -> None:
        gha.CONFIG_DIR.mkdir(parents=True)
        gha.CONFIG_PATH.write_text("github_app:\n  app_id: '0'\n")
        gha.KEY_PATH.write_text("KEY")
        os.chmod(gha.KEY_PATH, 0o600)

        runner = CliRunner()
        result = runner.invoke(gha.github_app, ["status"])

        assert result.exit_code == 0
        assert str(gha.CONFIG_PATH) in result.output
