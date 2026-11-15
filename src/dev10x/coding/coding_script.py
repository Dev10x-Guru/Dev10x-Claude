"""Where core's ``cli`` server finds the coding skill scripts after they moved
to ``dev10x-coding`` (GH-1572).

The git and GitHub MCP tools stay registered by core (ADR-0034, B9 and
GH-1563) while the skills that own the scripts ship in the satellite.
"""

from __future__ import annotations

from dev10x.core.paths import satellite_script
from dev10x.core.subprocess_utils import get_plugin_root

CODING_KEY = "coding"
CODING_PLUGIN_NAME = "dev10x-coding"


def coding_script(*, skill: str, rel: str) -> str:
    return satellite_script(
        plugin_root=get_plugin_root(),
        key=CODING_KEY,
        plugin_name=CODING_PLUGIN_NAME,
        skill=skill,
        rel=rel,
    )


__all__ = ["CODING_KEY", "CODING_PLUGIN_NAME", "coding_script"]
