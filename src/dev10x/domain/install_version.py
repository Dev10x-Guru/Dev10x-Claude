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
from typing import Any

import yaml

from dev10x.domain.common.result import Result, err, ok
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


def read_running_hook_version(*, plugin_root: Path | None = None) -> str | None:
    """Return the version that is *currently executing* inside this session.

    ``$CLAUDE_PLUGIN_ROOT`` is set by Claude Code to the plugin directory
    that was resolved when the session started. Hooks loaded from that
    directory run for the entire session lifetime — an on-disk upgrade
    does not swap them out. Reading the version from this directory gives
    us the *running* version, which may lag behind the latest installed
    version when the user ran ``claude plugin update`` mid-session.

    Returns ``None`` when the running root is unknown (e.g., local
    ``--plugin-dir`` dev runs that do not carry a versioned cache path).
    """
    root = plugin_root or _default_plugin_root()
    return read_plugin_version(plugin_root=root)


def read_latest_installed_version(
    *,
    cache_dir: Path | None = None,
    publisher: str = "Dev10x-Guru",
    plugin_slug: str = "dev10x-claude",
) -> str | None:
    """Return the highest-version directory under the plugin cache.

    Scans ``~/.claude/plugins/cache/<publisher>/<plugin_slug>/`` for
    semver-named subdirectories and returns the latest. Returns ``None``
    when the directory is absent or empty (e.g., ``--plugin-dir`` installs
    that bypass the cache).
    """
    from dev10x.domain.claude_paths import ClaudeDir

    root = cache_dir or (ClaudeDir.plugins_cache_dir() / publisher / plugin_slug)
    if not root.is_dir():
        return None
    versions = sorted(
        (d for d in root.iterdir() if d.is_dir()),
        key=lambda p: _version_tuple(p.name),
    )
    return versions[-1].name if versions else None


def _version_tuple(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in version.split("."))
    except ValueError:
        return (0,)


def record_upgrade(*, version: str | None = None) -> Result[dict[str, Any]]:
    """Record the currently-installed plugin version as applied.

    Resolves ``version`` (or the manifest version when omitted) and
    writes it to ``~/.claude/Dev10x/version.yml`` so the SessionStart
    install-check stops emitting upgrade prompts. Returns an error
    Result when no version can be resolved (ADR-0009).
    """
    resolved = version or read_plugin_version()
    if resolved is None:
        return err("Could not resolve plugin version from plugin.json")
    path = write_applied_version(plugin_version=resolved)
    return ok({"version": resolved, "path": str(path)})


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
    "read_latest_installed_version",
    "read_plugin_version",
    "read_running_hook_version",
    "record_upgrade",
    "write_applied_version",
]
