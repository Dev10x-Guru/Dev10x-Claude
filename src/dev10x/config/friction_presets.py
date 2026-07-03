"""Friction-preset hydration at the infra tier (ADR-0016 D-1, Q2).

The shipped presets and overlays live as data in ``presets/friction/``
(``<name>.yaml`` presets, ``overlays/<name>.yaml`` overlays). This module
reads them and returns the same dict structures the pure-domain resolver
(:mod:`dev10x.domain.gate_policy`) consumes — keeping file I/O out of the
domain per ADR-0007 D3. The MCP boundary injects the hydrated maps into
``resolve_gate``; a drift-guard test asserts the YAML stays identical to
the domain default constants.

User presets extend the shipped set from
``~/.config/Dev10x/friction-presets.yaml`` (ADR-0016 Q2), so a user can
define additional presets without editing the plugin.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from dev10x.subprocess_utils import get_plugin_root

_PRESET_SUBDIR = Path("presets") / "friction"
_OVERLAY_SUBDIR = _PRESET_SUBDIR / "overlays"

# ~/.config/Dev10x/friction-presets.yaml — user-defined presets that
# extend the shipped set. Shape: ``presets: {<name>: {<toggle>: <value>}}``.
USER_PRESETS_RELPATH = Path(".config") / "Dev10x" / "friction-presets.yaml"


def _load_mapping(path: Path) -> dict[str, Any]:
    """Load a YAML file into a mapping; degrade to ``{}`` on any failure."""
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, ValueError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _load_preset_dir(directory: Path) -> dict[str, dict[str, Any]]:
    """Load ``<stem>: {toggle: value}`` for every ``*.yaml`` in ``directory``.

    Non-recursive — the ``overlays/`` subdirectory is loaded separately so
    an overlay never masquerades as a full preset.
    """
    presets: dict[str, dict[str, Any]] = {}
    if not directory.is_dir():
        return presets
    for path in sorted(directory.glob("*.yaml")):
        mapping = _load_mapping(path)
        if mapping:
            presets[path.stem] = mapping
    return presets


def load_shipped_presets(*, plugin_root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Hydrate the shipped presets from ``presets/friction/*.yaml``."""
    root = plugin_root or get_plugin_root()
    return _load_preset_dir(root / _PRESET_SUBDIR)


def load_shipped_overlays(*, plugin_root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Hydrate the shipped overlays from ``presets/friction/overlays/*.yaml``."""
    root = plugin_root or get_plugin_root()
    return _load_preset_dir(root / _OVERLAY_SUBDIR)


def load_user_presets(*, home: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load user-defined presets from ``~/.config/Dev10x/friction-presets.yaml``.

    Returns ``{}`` when the file is absent, unreadable, malformed, or has
    no ``presets`` mapping — the shipped set then stands alone.
    """
    base = home or Path.home()
    path = base / USER_PRESETS_RELPATH
    if not path.exists():
        return {}
    presets = _load_mapping(path).get("presets")
    return presets if isinstance(presets, dict) else {}


__all__ = [
    "USER_PRESETS_RELPATH",
    "load_shipped_overlays",
    "load_shipped_presets",
    "load_user_presets",
]
