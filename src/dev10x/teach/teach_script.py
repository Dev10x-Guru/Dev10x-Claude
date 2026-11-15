"""Where core finds the skill-audit and skill-index scripts after they moved
to ``dev10x-teach`` (GH-1568).

The audit and skill-index MCP tools stay in core (ADR-0034, B5) while the
skills that own the scripts ship in the satellite.
"""

from __future__ import annotations

from dev10x.core.paths import satellite_script
from dev10x.core.subprocess_utils import get_plugin_root

TEACH_KEY = "teach"
TEACH_PLUGIN_NAME = "dev10x-teach"


def teach_script(*, skill: str, rel: str) -> str:
    return satellite_script(
        plugin_root=get_plugin_root(),
        key=TEACH_KEY,
        plugin_name=TEACH_PLUGIN_NAME,
        skill=skill,
        rel=rel,
    )


__all__ = ["TEACH_KEY", "TEACH_PLUGIN_NAME", "teach_script"]
