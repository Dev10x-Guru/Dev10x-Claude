"""Track the plugin version that was last applied by upgrade-cleanup.

Two versions matter:

* The **installed plugin version** — read from
  ``${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json``. This is what
  Claude Code is running right now.
* The **applied version** — the value the user most recently ran
  upgrade-cleanup against, stored in ``~/.claude/Dev10x/version.yml``.

When these diverge, the user has installed a new plugin release but
has not run the migrations/permission refresh that ships with it.
SessionStart consumes this to surface a guided prompt rather than
letting silent drift cause friction.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import yaml

from dev10x.domain.dev10x_paths import Dev10xConfigDir


def read_plugin_version(*, plugin_root: Path | None = None) -> str | None:
    """Return the version field from the active plugin's ``plugin.json``.

    Honors ``$CLAUDE_PLUGIN_ROOT`` when ``plugin_root`` is omitted.
    Returns ``None`` when the manifest is missing or unreadable.
    """
    root = plugin_root or _default_plugin_root()
    if root is None:
        return None
    manifest = root / ".claude-plugin" / "plugin.json"
    if not manifest.is_file():
        return None
    try:
        data = json.loads(manifest.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    version = data.get("version")
    return version if isinstance(version, str) else None


def read_applied_version(*, version_yaml: Path | None = None) -> str | None:
    """Return the plugin version last applied via upgrade-cleanup.

    Returns ``None`` when ``~/.claude/Dev10x/version.yml`` is absent or
    does not contain a ``plugin_version`` string.
    """
    path = version_yaml or Dev10xConfigDir.version_yaml()
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(data, dict):
        return None
    version = data.get("plugin_version")
    return version if isinstance(version, str) else None


def write_applied_version(
    *,
    plugin_version: str,
    version_yaml: Path | None = None,
    now: datetime | None = None,
) -> Path:
    """Record ``plugin_version`` as the latest version applied.

    Creates parent directories as needed. Returns the path written.
    """
    path = version_yaml or Dev10xConfigDir.version_yaml()
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = (now or datetime.now(UTC)).isoformat()
    payload = {"plugin_version": plugin_version, "upgraded_at": timestamp}
    path.write_text(yaml.safe_dump(payload, sort_keys=True))
    return path


def install_state() -> InstallState:
    """Summarize whether the Dev10x install is current.

    Combines the running plugin version, the applied version on disk,
    and whether the userspace config directory exists at all.
    """
    config_present = Dev10xConfigDir.home().is_dir()
    plugin_version = read_plugin_version()
    applied_version = read_applied_version() if config_present else None
    return InstallState(
        config_present=config_present,
        plugin_version=plugin_version,
        applied_version=applied_version,
    )


def _default_plugin_root() -> Path | None:
    env_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env_root:
        candidate = Path(env_root)
        if candidate.is_dir():
            return candidate
    walk_up = Path(__file__).resolve().parent.parent.parent.parent
    if (walk_up / ".claude-plugin" / "plugin.json").is_file():
        return walk_up
    return None


class InstallState:
    """Snapshot of the Dev10x install state on disk."""

    __slots__ = ("applied_version", "config_present", "plugin_version")

    def __init__(
        self,
        *,
        config_present: bool,
        plugin_version: str | None,
        applied_version: str | None,
    ) -> None:
        self.config_present = config_present
        self.plugin_version = plugin_version
        self.applied_version = applied_version

    @property
    def needs_bootstrap(self) -> bool:
        """True when the userspace config directory is missing entirely."""
        return not self.config_present

    @property
    def needs_upgrade(self) -> bool:
        """True when applied and plugin versions disagree.

        Returns False when either version is unknown — we only flag
        the case where both are known and differ, since "unknown
        applied version" is handled by :attr:`needs_bootstrap` once
        the config directory exists but lacks a version.yml file.
        """
        if self.plugin_version is None:
            return False
        if self.applied_version is None and self.config_present:
            return True
        return self.applied_version is not None and self.applied_version != self.plugin_version


__all__ = [
    "InstallState",
    "install_state",
    "read_applied_version",
    "read_plugin_version",
    "write_applied_version",
]
