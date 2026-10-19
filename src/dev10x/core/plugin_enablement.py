"""Whether a plugin key is enabled for a project (ADR-0034, GH-1557).

Claude Code records plugin enablement as ``enabledPlugins`` in three
settings files; for each id the most specific file wins:
``<project>/.claude/settings.local.json`` over
``<project>/.claude/settings.json`` over ``~/.claude/settings.json``.

During Stage A every plugin key ships inside ``dev10x``, so a key maps
to the core install id unless ``plugins.yaml`` lists it under
``extracted``. A settings file that cannot be read makes the key count
as enabled: the callers gate guardrails on this answer, and a guardrail
that silently stops guarding is the worse failure.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from dev10x.core.domain.claude_paths import ClaudeDir
from dev10x.core.plugin_map import PluginMap, expected_plugin_name, load_plugin_map
from dev10x.core.skills.permission.legacy_namespace import CURRENT_PLUGIN_ID, LEGACY_PLUGIN_ID

log = logging.getLogger(__name__)

ENABLED_PLUGINS_KEY = "enabledPlugins"


class PluginSettingsError(ValueError):
    pass


def settings_files(*, project_dir: Path | None) -> list[Path]:
    files = [ClaudeDir.settings_json()]
    if project_dir is not None:
        files.append(project_dir / ".claude" / "settings.json")
        files.append(project_dir / ".claude" / "settings.local.json")
    return files


def enabled_plugins(*, project_dir: Path | None) -> dict[str, bool]:
    merged: dict[str, bool] = {}
    for layer in _layers(project_dir=project_dir):
        merged.update(layer)
    return merged


def plugin_ids(*, key: str, plugin_map: PluginMap) -> frozenset[str]:
    if plugin_map.is_extracted(key=key):
        name = plugin_map.plugin_name(key=key) or expected_plugin_name(key=key)
        return frozenset({f"{name}@{plugin_map.marketplace}".casefold()})
    return frozenset({CURRENT_PLUGIN_ID.casefold(), LEGACY_PLUGIN_ID.casefold()})


def is_plugin_enabled(
    *,
    key: str,
    project_dir: Path | None,
    plugin_map: PluginMap | None = None,
) -> bool:
    plugin_map = plugin_map or load_plugin_map()
    try:
        layers = _layers(project_dir=project_dir)
    except PluginSettingsError as exc:
        log.warning("plugin enablement unreadable; treating %s as enabled: %s", key, exc)
        return True
    ids = plugin_ids(key=key, plugin_map=plugin_map)
    # Matched case-insensitively per layer, so a legacy `Dev10x@…` key in a
    # broader file never outranks a current-spelling key in a narrower one.
    for layer in reversed(layers):
        matches = [value for plugin_id, value in layer.items() if plugin_id.casefold() in ids]
        if matches:
            return any(matches)
    # An unextracted key ships inside the plugin running this code, which is
    # loaded even when no settings file names it (e.g. `claude --plugin-dir`).
    return not plugin_map.is_extracted(key=key)


def _layers(*, project_dir: Path | None) -> list[dict[str, bool]]:
    return [_enabled_in(path=path) for path in settings_files(project_dir=project_dir)]


def _enabled_in(*, path: Path) -> dict[str, bool]:
    try:
        text = path.read_text()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise PluginSettingsError(f"{path}: {exc}") from exc
    try:
        document: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PluginSettingsError(f"{path}: {exc}") from exc
    if not isinstance(document, dict):
        raise PluginSettingsError(f"{path}: settings must be a JSON object")
    plugins = document.get(ENABLED_PLUGINS_KEY, {})
    if not isinstance(plugins, dict):
        raise PluginSettingsError(f"{path}: `{ENABLED_PLUGINS_KEY}` must be an object")
    return {str(plugin_id): bool(value) for plugin_id, value in plugins.items()}


__all__ = [
    "ENABLED_PLUGINS_KEY",
    "PluginSettingsError",
    "enabled_plugins",
    "is_plugin_enabled",
    "plugin_ids",
    "settings_files",
]
