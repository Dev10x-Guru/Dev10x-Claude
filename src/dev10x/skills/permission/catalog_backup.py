"""Restore catalog-managed settings files from their backups (GH-1432).

The write side of backups is structural — every writer goes through
:func:`dev10x.skills.permission.backup.backed_up_write` (GH-1429). This
module is the ``update-paths --restore`` operation: resolve the same
settings files the writers target and roll each back. Split out of
``update_paths.py`` by GH-1432.
"""

from pathlib import Path

from dev10x.skills.permission.catalog_load import find_settings_files, load_config


def _restore(*, config_path: Path) -> int:
    from dev10x.skills.permission.backup import restore_report

    config = load_config(config_path)
    settings_files = find_settings_files(
        roots=config.get("roots", []),
        include_user=config.get("include_user_settings", True),
    )
    code, report = restore_report(paths=settings_files)
    print(report)
    return code
