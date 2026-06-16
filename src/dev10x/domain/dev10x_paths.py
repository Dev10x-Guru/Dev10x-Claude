"""Canonical Dev10x config paths, independent of ``~/.claude``.

GH-215: Dev10x's userspace config moves out of ``~/.claude/`` so the
plugin no longer depends on Claude Code's home directory layout.

Default root resolution (in order):
1. ``DEV10X_CONFIG_HOME`` env var (test/CI override)
2. ``$XDG_CONFIG_HOME/Dev10x`` if ``XDG_CONFIG_HOME`` is set
3. ``%APPDATA%/Dev10x`` on Windows
4. ``~/.config/Dev10x`` everywhere else (Linux, macOS, BSDs)

Lazy migration: every accessor checks the legacy ``~/.claude/...``
location on first call. If the legacy file/dir exists and the new
path does not, the legacy content is copied across. The legacy
entry is left in place so a downgrade can still read it; eager
cleanup invoked from ``Dev10x:upgrade-cleanup`` and ``Dev10x:plugin-doctor``
removes the legacy entries once parity is confirmed.
"""

from __future__ import annotations

import functools
import logging
import os
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

from dev10x.domain.claude_paths import ClaudeDir

CONFIG_HOME_ENV_VAR = "DEV10X_CONFIG_HOME"
XDG_CONFIG_HOME_ENV_VAR = "XDG_CONFIG_HOME"

_log = logging.getLogger(__name__)


def _platform_default_root() -> Path:
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Dev10x"
    xdg = os.environ.get(XDG_CONFIG_HOME_ENV_VAR)
    if xdg:
        return Path(xdg) / "Dev10x"
    return Path.home() / ".config" / "Dev10x"


@functools.cache
def _resolve_path(*, override: str | None, segments: tuple[str, ...]) -> Path:
    base = Path(override).expanduser() if override else _platform_default_root()
    return base.joinpath(*segments) if segments else base


def _copy(*, source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True)
    else:
        shutil.copy2(source, destination)


def migrate_path(*, legacy: Path, current: Path) -> bool:
    """Copy ``legacy`` to ``current`` when only the legacy path exists.

    Returns True when a copy happened. Leaves the legacy path in
    place so a downgrade can still read it; eager cleanup deletes
    the legacy entry once parity is confirmed.
    """
    if current.exists() or not legacy.exists():
        return False
    _log.info("Migrating Dev10x config: %s -> %s", legacy, current)
    _copy(source=legacy, destination=current)
    return True


class Dev10xConfigDir:
    """Cached accessors for canonical Dev10x config paths.

    ``DEV10X_CONFIG_HOME`` overrides the root. Each accessor runs
    lazy migration from the legacy ``~/.claude/`` location on first
    call — see :func:`migrate_path`.
    """

    @classmethod
    def _resolve(cls, *segments: str) -> Path:
        return _resolve_path(
            override=os.environ.get(CONFIG_HOME_ENV_VAR),
            segments=segments,
        )

    @classmethod
    def reset_cache(cls) -> None:
        """Clear the path resolution cache. Call in test teardown."""
        _resolve_path.cache_clear()

    @classmethod
    def home(cls) -> Path:
        return cls._resolve()

    @classmethod
    def version_yaml(cls) -> Path:
        return _with_lazy_migration(cls._resolve("version.yml"), _legacy_version_yaml)

    @classmethod
    def projects_yaml(cls) -> Path:
        return _with_lazy_migration(cls._resolve("projects.yaml"), _legacy_projects_yaml)

    @classmethod
    def platforms_yaml(cls) -> Path:
        return _with_lazy_migration(cls._resolve("platforms.yaml"), _legacy_platforms_yaml)

    @classmethod
    def slack_config_yaml(cls) -> Path:
        return _with_lazy_migration(
            cls._resolve("slack-config.yaml"),
            _legacy_slack_config_yaml,
        )

    @classmethod
    def slack_review_config_yaml(cls) -> Path:
        return _with_lazy_migration(
            cls._resolve("slack-config-code-review-requests.yaml"),
            _legacy_slack_review_config_yaml,
        )

    @classmethod
    def upgrade_cleanup_projects_yaml(cls) -> Path:
        return _with_lazy_migration(
            cls._resolve("upgrade-cleanup-projects.yaml"),
            _legacy_upgrade_cleanup_projects_yaml,
        )

    @classmethod
    def github_bot_dir(cls) -> Path:
        return _with_lazy_migration(cls._resolve("github-bot"), _legacy_github_bot_dir)

    @classmethod
    def github_app_yaml(cls) -> Path:
        return _with_lazy_migration(
            cls._resolve("github-bot", "github-app.yaml"),
            _legacy_github_app_yaml,
        )

    @classmethod
    def gitmoji_yaml(cls) -> Path:
        return _with_lazy_migration(cls._resolve("gitmoji.yaml"), _legacy_gitmoji_yaml)

    @classmethod
    def github_reviewers_config_yaml(cls) -> Path:
        return _with_lazy_migration(
            cls._resolve("github-reviewers-config.yaml"),
            _legacy_github_reviewers_config_yaml,
        )

    @classmethod
    def settings_pr_merge_yaml(cls) -> Path:
        return _with_lazy_migration(
            cls._resolve("settings-pr-merge.yaml"),
            _legacy_settings_pr_merge_yaml,
        )


def _with_lazy_migration(current: Path, legacy_provider: Callable[[], Path]) -> Path:
    migrate_path(legacy=legacy_provider(), current=current)
    return current


# Legacy path providers — wrapped in callables so test overrides of
# ClaudeDir env vars propagate on every call.
_legacy_version_yaml = ClaudeDir.dev10x_version_yaml
_legacy_projects_yaml = ClaudeDir.memory_projects_yaml
_legacy_platforms_yaml = ClaudeDir.platforms_yaml
_legacy_slack_config_yaml = ClaudeDir.slack_config_yaml
_legacy_slack_review_config_yaml = ClaudeDir.slack_review_config_yaml
_legacy_upgrade_cleanup_projects_yaml = ClaudeDir.upgrade_cleanup_projects_yaml
_legacy_github_bot_dir = ClaudeDir.github_bot_dir
_legacy_github_app_yaml = ClaudeDir.github_app_yaml
_legacy_gitmoji_yaml = ClaudeDir.gitmoji_yaml
_legacy_github_reviewers_config_yaml = ClaudeDir.github_reviewers_config_yaml
_legacy_settings_pr_merge_yaml = ClaudeDir.settings_pr_merge_yaml


def _legacy_plugin_maintenance_prefs_yaml() -> Path:
    return ClaudeDir.memory_dev10x_dir() / "plugin-maintenance-prefs.yaml"


def _legacy_playbooks_dir() -> Path:
    return ClaudeDir.memory_dev10x_dir() / "playbooks"


def _migration_pairs() -> list[tuple[Path, Path]]:
    """Build (legacy, current) pairs without triggering lazy migration."""
    return [
        (_legacy_version_yaml(), Dev10xConfigDir._resolve("version.yml")),
        (_legacy_projects_yaml(), Dev10xConfigDir._resolve("projects.yaml")),
        (_legacy_platforms_yaml(), Dev10xConfigDir._resolve("platforms.yaml")),
        (_legacy_slack_config_yaml(), Dev10xConfigDir._resolve("slack-config.yaml")),
        (
            _legacy_slack_review_config_yaml(),
            Dev10xConfigDir._resolve("slack-config-code-review-requests.yaml"),
        ),
        (
            _legacy_upgrade_cleanup_projects_yaml(),
            Dev10xConfigDir._resolve("upgrade-cleanup-projects.yaml"),
        ),
        (_legacy_github_bot_dir(), Dev10xConfigDir._resolve("github-bot")),
        (
            _legacy_github_app_yaml(),
            Dev10xConfigDir._resolve("github-bot", "github-app.yaml"),
        ),
        (_legacy_playbooks_dir(), Dev10xConfigDir._resolve("playbooks")),
        (_legacy_gitmoji_yaml(), Dev10xConfigDir._resolve("gitmoji.yaml")),
        (
            _legacy_github_reviewers_config_yaml(),
            Dev10xConfigDir._resolve("github-reviewers-config.yaml"),
        ),
        (
            _legacy_settings_pr_merge_yaml(),
            Dev10xConfigDir._resolve("settings-pr-merge.yaml"),
        ),
        (
            _legacy_plugin_maintenance_prefs_yaml(),
            Dev10xConfigDir._resolve("plugin-maintenance-prefs.yaml"),
        ),
    ]


def migrate_all() -> list[Path]:
    """Eagerly migrate every known legacy file. Returns paths copied."""
    migrated: list[Path] = []
    for legacy, current in _migration_pairs():
        if migrate_path(legacy=legacy, current=current):
            migrated.append(current)
    return migrated


def stale_legacy_paths() -> list[Path]:
    """Return legacy paths that still exist (doctor uses this to nudge)."""
    return [legacy for legacy, _ in _migration_pairs() if legacy.exists()]


__all__ = [
    "CONFIG_HOME_ENV_VAR",
    "Dev10xConfigDir",
    "migrate_all",
    "migrate_path",
    "stale_legacy_paths",
]
