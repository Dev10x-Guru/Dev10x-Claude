"""Tests for the backup utility module."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from dev10x.skills.permission.backup import (
    create_backup,
    find_backups,
    find_latest_backup,
    restore_all,
    restore_backup,
    restore_report,
)


class TestCreateBackup:
    @pytest.fixture()
    def settings_file(self, tmp_path: Path) -> Path:
        path = tmp_path / "settings.local.json"
        path.write_text(json.dumps({"permissions": {"allow": ["Bash(git log:*)"]}}) + "\n")
        return path

    def test_creates_timestamped_backup(self, settings_file: Path) -> None:
        result = create_backup(settings_file)

        assert result is not None
        assert result.exists()
        assert ".bak." in result.name
        assert result.read_text() == settings_file.read_text()

    def test_returns_none_for_nonexistent_file(self, tmp_path: Path) -> None:
        result = create_backup(tmp_path / "nonexistent.json")

        assert result is None

    def test_backup_name_contains_timestamp(self, settings_file: Path) -> None:
        with patch("dev10x.skills.permission.backup.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "20260414T120000Z"
            result = create_backup(settings_file)

        assert result is not None
        assert result.name == "settings.local.json.bak.20260414T120000Z"

    def test_multiple_backups_have_different_names(self, settings_file: Path) -> None:
        with patch("dev10x.skills.permission.backup.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "20260414T120000Z"
            first = create_backup(settings_file)
            mock_dt.now.return_value.strftime.return_value = "20260414T120001Z"
            second = create_backup(settings_file)

        assert first != second
        assert first.exists()
        assert second.exists()


class TestFindBackups:
    @pytest.fixture()
    def settings_file(self, tmp_path: Path) -> Path:
        path = tmp_path / "settings.local.json"
        path.write_text("{}")
        return path

    def test_finds_existing_backups(self, settings_file: Path) -> None:
        (settings_file.parent / "settings.local.json.bak.20260414T100000Z").write_text("{}")
        (settings_file.parent / "settings.local.json.bak.20260414T110000Z").write_text("{}")

        result = find_backups(settings_file)

        assert len(result) == 2

    def test_returns_empty_when_no_backups(self, settings_file: Path) -> None:
        result = find_backups(settings_file)

        assert result == []

    def test_returns_sorted_by_name(self, settings_file: Path) -> None:
        (settings_file.parent / "settings.local.json.bak.20260414T120000Z").write_text("{}")
        (settings_file.parent / "settings.local.json.bak.20260414T100000Z").write_text("{}")

        result = find_backups(settings_file)

        assert result[0].name < result[1].name


class TestFindLatestBackup:
    @pytest.fixture()
    def settings_file(self, tmp_path: Path) -> Path:
        path = tmp_path / "settings.local.json"
        path.write_text("{}")
        return path

    def test_returns_latest_backup(self, settings_file: Path) -> None:
        (settings_file.parent / "settings.local.json.bak.20260414T100000Z").write_text("old")
        (settings_file.parent / "settings.local.json.bak.20260414T120000Z").write_text("new")

        result = find_latest_backup(settings_file)

        assert result is not None
        assert "120000" in result.name

    def test_returns_none_when_no_backups(self, settings_file: Path) -> None:
        result = find_latest_backup(settings_file)

        assert result is None


class TestRestoreBackup:
    @pytest.fixture()
    def settings_file(self, tmp_path: Path) -> Path:
        path = tmp_path / "settings.local.json"
        path.write_text('{"modified": true}')
        return path

    def test_restores_from_latest_backup(self, settings_file: Path) -> None:
        backup = settings_file.parent / "settings.local.json.bak.20260414T100000Z"
        backup.write_text('{"original": true}')

        result = restore_backup(settings_file)

        assert result == backup
        assert settings_file.read_text() == '{"original": true}'

    def test_restores_from_explicit_backup(self, settings_file: Path) -> None:
        backup = settings_file.parent / "settings.local.json.bak.20260414T100000Z"
        backup.write_text('{"explicit": true}')

        result = restore_backup(settings_file, backup=backup)

        assert result == backup
        assert settings_file.read_text() == '{"explicit": true}'

    def test_returns_none_when_no_backup_exists(self, settings_file: Path) -> None:
        result = restore_backup(settings_file)

        assert result is None
        assert settings_file.read_text() == '{"modified": true}'


class TestRestoreAll:
    def test_restores_multiple_files(self, tmp_path: Path) -> None:
        file_a = tmp_path / "a" / "settings.local.json"
        file_b = tmp_path / "b" / "settings.local.json"
        file_a.parent.mkdir()
        file_b.parent.mkdir()
        file_a.write_text('{"a": "modified"}')
        file_b.write_text('{"b": "modified"}')
        (file_a.parent / "settings.local.json.bak.20260414T100000Z").write_text('{"a": "orig"}')
        (file_b.parent / "settings.local.json.bak.20260414T100000Z").write_text('{"b": "orig"}')

        result = restore_all(paths=[file_a, file_b])

        assert len(result) == 2
        assert file_a.read_text() == '{"a": "orig"}'
        assert file_b.read_text() == '{"b": "orig"}'

    def test_skips_files_without_backups(self, tmp_path: Path) -> None:
        file_a = tmp_path / "a" / "settings.local.json"
        file_a.parent.mkdir()
        file_a.write_text('{"a": "modified"}')

        result = restore_all(paths=[file_a])

        assert result == []
        assert file_a.read_text() == '{"a": "modified"}'


class TestRestoreReport:
    def test_reports_restored_files(self, tmp_path: Path) -> None:
        file_a = tmp_path / "settings.local.json"
        file_a.write_text('{"a": "modified"}')
        backup = tmp_path / "settings.local.json.bak.20260414T100000Z"
        backup.write_text('{"a": "orig"}')

        code, message = restore_report(paths=[file_a])

        assert code == 0
        assert file_a.read_text() == '{"a": "orig"}'
        assert "Restored 1 files." in message
        assert backup.name in message

    def test_reports_when_no_backups(self, tmp_path: Path) -> None:
        file_a = tmp_path / "settings.local.json"
        file_a.write_text('{"a": "modified"}')

        code, message = restore_report(paths=[file_a])

        assert code == 0
        assert message == "No backups found to restore."
        assert file_a.read_text() == '{"a": "modified"}'
