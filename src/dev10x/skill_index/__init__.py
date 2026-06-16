"""Skill index MCP tool implementations.

Wraps generate-all.sh as an MCP tool so skills can regenerate
the skill index without Bash allow-rule friction.
"""

from __future__ import annotations

from typing import Any

from dev10x.domain.common.result import Result, err, ok
from dev10x.skill_index.builder import SkillEntry, scan_skill_dirs
from dev10x.skill_index.catalog import SkillCatalog
from dev10x.subprocess_utils import async_run_script

__all__ = ["SkillCatalog", "SkillEntry", "generate_all", "scan_skill_dirs"]


async def generate_all(
    *,
    force: bool = False,
) -> Result[dict[str, Any]]:
    args: list[str] = []
    if force:
        args.append("--force")

    result = await async_run_script(
        "skills/skill-index/scripts/generate-all.sh",
        *args,
    )

    if result.returncode != 0:
        return err(result.stderr.strip())

    return ok({"success": True, "output": result.stdout.strip()})
