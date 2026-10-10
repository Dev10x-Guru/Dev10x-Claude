"""Tolerant YAML-mapping load shared by the three session-config documents.

``friction_yaml``, ``config_yaml`` and ``session_yaml`` each read a
hand-editable YAML file on a hot path (SessionStart, every gate
resolution). All three need the same degradation contract, so it lives
once here rather than in whichever document happened to define it first
(GH-1431).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Tolerantly load a YAML mapping, degrading to ``{}`` on any failure.

    A missing, unreadable, or malformed file — including an undecodable
    one (``ValueError`` covers ``UnicodeDecodeError``) — must degrade to
    the soft fallbacks rather than crash the SessionStart hook.
    """
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, ValueError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


__all__ = ["load_yaml_mapping"]
