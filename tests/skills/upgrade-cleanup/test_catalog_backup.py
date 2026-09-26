"""Tests for catalog_backup.py: the `update-paths --restore` operation
(GH-1432, GH-1449).

Previously untested — `_restore` had zero direct coverage anywhere in the
suite despite being a live CLI entry point (`dev10x permission
update-paths --restore`)."""

from pathlib import Path
from unittest.mock import patch

from dev10x.skills.permission.catalog_backup import _restore


class TestRestore:
    def test_resolves_settings_files_from_config_and_restores(self, tmp_path: Path) -> None:
        config_path = tmp_path / "projects.yaml"
        config_path.write_text("roots: [/work/example]\ninclude_user_settings: false\n")
        resolved_files = [tmp_path / "settings.local.json"]

        with (
            patch(
                "dev10x.skills.permission.catalog_backup.find_settings_files",
                return_value=resolved_files,
            ) as mock_find,
            patch(
                "dev10x.skills.permission.backup.restore_report",
                return_value=(0, "Restored 1 files."),
            ) as mock_restore,
        ):
            code = _restore(config_path=config_path)

        assert code == 0
        mock_find.assert_called_once_with(roots=["/work/example"], include_user=False)
        mock_restore.assert_called_once_with(paths=resolved_files)

    def test_defaults_include_user_settings_true_when_key_absent(self, tmp_path: Path) -> None:
        config_path = tmp_path / "projects.yaml"
        config_path.write_text("roots: []\n")

        with (
            patch(
                "dev10x.skills.permission.catalog_backup.find_settings_files",
                return_value=[],
            ) as mock_find,
            patch(
                "dev10x.skills.permission.backup.restore_report",
                return_value=(0, "No backups found to restore."),
            ),
        ):
            _restore(config_path=config_path)

        assert mock_find.call_args.kwargs["include_user"] is True

    def test_propagates_restore_report_exit_code(self, tmp_path: Path) -> None:
        config_path = tmp_path / "projects.yaml"
        config_path.write_text("roots: []\n")

        with (
            patch(
                "dev10x.skills.permission.catalog_backup.find_settings_files",
                return_value=[],
            ),
            patch(
                "dev10x.skills.permission.backup.restore_report",
                return_value=(1, "  ERROR: something went wrong"),
            ),
        ):
            code = _restore(config_path=config_path)

        assert code == 1

    def test_prints_the_report(self, tmp_path: Path, capsys) -> None:
        config_path = tmp_path / "projects.yaml"
        config_path.write_text("roots: []\n")

        with (
            patch(
                "dev10x.skills.permission.catalog_backup.find_settings_files",
                return_value=[],
            ),
            patch(
                "dev10x.skills.permission.backup.restore_report",
                return_value=(0, "No backups found to restore."),
            ),
        ):
            _restore(config_path=config_path)

        assert "No backups found to restore." in capsys.readouterr().out
