"""Strategy: satellite-dependencies (GH-1571, ADR-0034 Key rule 3).

Every satellite plugin declares ``"dependencies": ["dev10x", …]`` in its
manifest, and Claude Code starts a dependency of an enabled plugin
enabled. That native edge is the primary guard; this strategy is the
backup the ADR keeps for it. A satellite enabled while ``dev10x`` (or a
hard dependency from ``plugins.yaml``) is switched off in a narrower
settings file runs without the MCP server, hooks and safety floor its
skills assume.

An explicit ``false`` is ``drift``: someone turned the dependency off.
A dependency no settings file names is only a ``suggestion``, because
the native dependency field normally enables it without a settings
entry, so its absence is not evidence of a broken install.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dev10x.core.plugin_enablement import ENABLED_PLUGINS_KEY, plugin_ids
from dev10x.core.plugin_map import CORE_KEY, PluginMap, load_plugin_map
from dev10x.core.skills.doctor.strategy import Context, Finding, Remediation, Severity, Strategy

STRATEGY_ID = "satellite-dependencies"


@dataclass(frozen=True)
class SatelliteDependencyRemediation:
    """Remediation payload: one dependency to enable for a satellite."""

    settings_path: str
    satellite_id: str
    dependency_id: str

    def to_remediation(self, *, finding: Finding) -> Remediation:
        return Remediation(
            kind="edit_settings",
            target=self.settings_path,
            action={
                "bucket": ENABLED_PLUGINS_KEY,
                "set": {self.dependency_id: True},
                "required_by": self.satellite_id,
            },
        )


@dataclass(frozen=True)
class _Enablement:
    value: bool
    source: Path


def _enabled_plugins(*, path: Path) -> dict[str, bool]:
    try:
        document: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    plugins = document.get(ENABLED_PLUGINS_KEY) if isinstance(document, dict) else None
    if not isinstance(plugins, dict):
        return {}
    return {str(plugin_id).casefold(): bool(value) for plugin_id, value in plugins.items()}


def _merged(*, settings_paths: tuple[Path, ...]) -> dict[str, _Enablement]:
    merged: dict[str, _Enablement] = {}
    for path in dict.fromkeys(settings_paths):
        for plugin_id, value in _enabled_plugins(path=path).items():
            merged[plugin_id] = _Enablement(value=value, source=path)
    return merged


def _state(*, ids: frozenset[str], merged: dict[str, _Enablement]) -> _Enablement | None:
    matches = [merged[plugin_id] for plugin_id in sorted(ids) if plugin_id in merged]
    enabled = [match for match in matches if match.value]
    return enabled[0] if enabled else (matches[0] if matches else None)


def _install_id(*, key: str, plugin_map: PluginMap) -> str:
    return f"{plugin_map.installed_name(key=key)}@{plugin_map.marketplace}"


def _dependency_keys(*, key: str, plugin_map: PluginMap) -> tuple[str, ...]:
    return (CORE_KEY, *plugin_map.dependencies.get(key, ()))


def _finding(
    *,
    satellite: _Enablement,
    satellite_id: str,
    dependency_id: str,
    dependency: _Enablement | None,
) -> Finding:
    disabled = dependency is not None
    severity: Severity = "drift" if disabled else "suggestion"
    where = dependency.source if dependency is not None else satellite.source
    state = f"is disabled in {where}" if disabled else "is not enabled in any settings file"
    return Finding(
        strategy_id=STRATEGY_ID,
        severity=severity,
        location=f"{where}:{ENABLED_PLUGINS_KEY}",
        evidence=(
            f"``{satellite_id}`` is enabled (in {satellite.source}) but its dependency "
            f"``{dependency_id}`` {state}; the satellite's skills call MCP tools and "
            "rely on hooks that only the dependency ships."
        ),
        proposed_fix=(
            f"Set ``{dependency_id}`` to true in {where}, or disable ``{satellite_id}``."
        ),
        data=SatelliteDependencyRemediation(
            settings_path=str(where),
            satellite_id=satellite_id,
            dependency_id=dependency_id,
        ),
    )


def detect_with_map(context: Context, *, plugin_map: PluginMap) -> list[Finding]:
    """Report each enabled satellite whose declared dependency is not enabled."""
    merged = _merged(settings_paths=context.settings_paths)
    findings: list[Finding] = []
    for key in plugin_map.extracted:
        satellite = _state(ids=plugin_ids(key=key, plugin_map=plugin_map), merged=merged)
        if satellite is None or not satellite.value:
            continue
        for dependency_key in _dependency_keys(key=key, plugin_map=plugin_map):
            ids = plugin_ids(key=dependency_key, plugin_map=plugin_map)
            dependency = _state(ids=ids, merged=merged)
            if dependency is not None and dependency.value:
                continue
            findings.append(
                _finding(
                    satellite=satellite,
                    satellite_id=_install_id(key=key, plugin_map=plugin_map),
                    dependency_id=_install_id(key=dependency_key, plugin_map=plugin_map),
                    dependency=dependency,
                )
            )
    return findings


def detect(context: Context) -> list[Finding]:
    """Report enabled satellites whose dependencies are off, per ``plugins.yaml``."""
    return detect_with_map(context, plugin_map=load_plugin_map())


def remediate(finding: Finding) -> Remediation:
    """Propose enabling the missing dependency where it was turned off."""
    return finding.to_remediation()


STRATEGY = Strategy(
    id=STRATEGY_ID,
    description=(
        "Flag an enabled satellite plugin whose manifest dependency — `dev10x` "
        "or a hard dependency from plugins.yaml — is disabled or not enabled "
        "anywhere (GH-1571)."
    ),
    detect=detect,
    remediate=remediate,
)
