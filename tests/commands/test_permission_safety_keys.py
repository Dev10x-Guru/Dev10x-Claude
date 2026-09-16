"""Tests for `dev10x permission ensure-safety-keys` and `doctor safety-keys` (GH-1320)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from dev10x.commands.permission import doctor as doctor_group
from dev10x.commands.permission import ensure_safety_keys as ensure_safety_keys_cmd
from dev10x.domain.common.result import ok
from dev10x.permission.service import PermissionContext


def _with_settings_files(monkeypatch: pytest.MonkeyPatch, files: list[Path]) -> None:
    import dev10x.commands.permission as cmd

    context = PermissionContext(
        config_path=Path("/config.yaml"),
        config={},
        settings_files=files,
    )
    monkeypatch.setattr(cmd, "load_permission_context", lambda **_kw: ok(context))


@pytest.fixture()
def settings_file(tmp_path: Path) -> Path:
    path = tmp_path / "settings.local.json"
    path.write_text("{}\n")
    return path


class TestEnsureSafetyKeysCommand:
    def test_seeds_both_keys(self, settings_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _with_settings_files(monkeypatch, [settings_file])

        result = CliRunner().invoke(ensure_safety_keys_cmd, [])

        assert result.exit_code == 0
        data = json.loads(settings_file.read_text())
        assert data["disableAutoMode"] == "disable"
        assert data["disableBypassPermissionsMode"] == "disable"

    def test_dry_run_writes_nothing(
        self, settings_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _with_settings_files(monkeypatch, [settings_file])
        before = settings_file.read_text()

        result = CliRunner().invoke(ensure_safety_keys_cmd, ["--dry-run"])

        assert result.exit_code == 0
        assert settings_file.read_text() == before

    def test_no_settings_files_is_reported_not_crashed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _with_settings_files(monkeypatch, [])

        result = CliRunner().invoke(ensure_safety_keys_cmd, [])

        assert result.exit_code == 0


class TestDoctorSafetyKeysCommand:
    def test_clean_file_exits_zero(
        self, settings_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings_file.write_text(
            json.dumps({"disableAutoMode": "disable", "disableBypassPermissionsMode": "disable"})
        )
        _with_settings_files(monkeypatch, [settings_file])

        result = CliRunner().invoke(doctor_group, ["safety-keys"])

        assert result.exit_code == 0

    def test_missing_key_exits_nonzero(
        self, settings_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _with_settings_files(monkeypatch, [settings_file])

        result = CliRunner().invoke(doctor_group, ["safety-keys"])

        assert result.exit_code == 1
        assert "disableAutoMode" in result.output

    def test_invalid_boolean_value_exits_nonzero(
        self, settings_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings_file.write_text(
            json.dumps({"disableAutoMode": True, "disableBypassPermissionsMode": True})
        )
        _with_settings_files(monkeypatch, [settings_file])

        result = CliRunner().invoke(doctor_group, ["safety-keys"])

        assert result.exit_code == 1
        assert "invalid" in result.output

    def test_no_settings_files_is_reported_not_crashed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _with_settings_files(monkeypatch, [])

        result = CliRunner().invoke(doctor_group, ["safety-keys"])

        assert result.exit_code == 0
