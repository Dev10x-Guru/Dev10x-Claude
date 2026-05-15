"""Plan sync MCP tool implementations.

Wraps the `dev10x.plan.service` transaction layer as async MCP
tools so skills can update plan context, retrieve summaries, and
archive plans without Bash allow-rule friction.
"""

from __future__ import annotations

from typing import Any

from dev10x.plan.service import (
    PlanServiceError,
    archive_plan,
    plan_summary,
    set_plan_context,
)


async def set_context(*, args: list[str]) -> dict[str, Any]:
    try:
        updated = set_plan_context(args=args)
    except PlanServiceError as exc:
        return {"error": str(exc)}
    return {"success": True, "updated_keys": updated}


async def json_summary() -> dict[str, Any]:
    try:
        return plan_summary()
    except PlanServiceError as exc:
        return {"error": str(exc)}


async def archive() -> dict[str, Any]:
    try:
        result = archive_plan()
    except PlanServiceError as exc:
        return {"error": str(exc)}
    if not result["archived"]:
        return {"success": True, "message": "No plan file to archive"}
    return {"success": True, "archive_name": result["archive_name"]}
