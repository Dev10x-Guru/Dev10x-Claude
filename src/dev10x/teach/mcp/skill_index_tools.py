"""Skill-index MCP tool registrations (split from misc_tools.py, GH-1548)."""

from __future__ import annotations

from dev10x.domain.common.result import to_wire
from dev10x.mcp._app import server


@server.tool()
async def generate_skill_index(
    force: bool = False,
) -> dict:
    """Generate SKILLS.md and .skills-menu.txt files.

    Args:
        force: Regenerate even when cache is fresh

    Returns:
        Dictionary with keys: success (bool), output (str)
    """
    from dev10x.teach import skill_index as idx

    return to_wire(await idx.generate_all(force=force))
