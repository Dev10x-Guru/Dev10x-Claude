"""Skill index MCP tool implementations.

Wraps generate-all.sh as an MCP tool so skills can regenerate
the skill index without Bash allow-rule friction.
"""

from __future__ import annotations

from typing import Any

from dev10x.subprocess_utils import async_run_script


async def generate_all(
    *,
    force: bool = False,
) -> dict[str, Any]:
    args: list[str] = []
    if force:
        args.append("--force")

    result = await async_run_script(
        "skills/skill-index/scripts/generate-all.sh",
        *args,
    )

    if result.returncode != 0:
        return {"error": result.stderr.strip()}

    return {"success": True, "output": result.stdout.strip()}
