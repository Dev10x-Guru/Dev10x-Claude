"""YAML-mapping loads shared by the hand-editable config documents.

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


class YamlMappingError(ValueError):
    pass


def read_yaml_mapping(path: Path) -> dict[str, Any]:
    """Load a YAML mapping, raising ``YamlMappingError`` naming the file.

    A missing or empty file is an empty mapping, not an error: both mean
    nothing has been configured yet. An unreadable or undecodable file,
    invalid YAML, or a top level that is not a mapping all raise.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise YamlMappingError(f"{path} is unreadable: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except (ValueError, yaml.YAMLError) as exc:
        raise YamlMappingError(f"{path} is not valid YAML: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise YamlMappingError(f"{path} must hold a mapping")
    return data


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Tolerantly load a YAML mapping, degrading to ``{}`` on any failure.

    A missing, unreadable, or malformed file — including an undecodable
    one (``ValueError`` covers ``UnicodeDecodeError``) — must degrade to
    the soft fallbacks rather than crash the SessionStart hook.
    """
    try:
        return read_yaml_mapping(path)
    except YamlMappingError:
        return {}


__all__ = ["YamlMappingError", "load_yaml_mapping", "read_yaml_mapping"]
