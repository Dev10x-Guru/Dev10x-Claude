"""Plan sync MCP tool implementations.

Wraps task-plan-sync operations as MCP tools so skills can
update plan context, retrieve summaries, and archive plans
without Bash allow-rule friction.
"""

from __future__ import annotations

from typing import Any


async def set_context(*, args: list[str]) -> dict[str, Any]:
    from dev10x.hooks.task_plan_sync import (
        Plan,
        get_plan_path,
        get_toplevel,
    )

    toplevel = get_toplevel()
    if not toplevel:
        return {"error": "Not in a git repository"}

    plan_path = get_plan_path(toplevel=toplevel)
    plan = Plan.load(path=plan_path)
    plan.ensure_metadata()

    for arg in args:
        if "=" not in arg:
            return {"error": f"Invalid argument (expected K=V): {arg}"}
        key, value = arg.split("=", 1)
        plan.set_context(key=key, value=value)

    plan.save(path=plan_path)
    context = plan.metadata.get("context", {})
    return {"success": True, "updated_keys": list(context.keys())}


async def json_summary() -> dict[str, Any]:
    from dev10x.hooks.task_plan_sync import (
        Plan,
        get_plan_path,
        get_toplevel,
    )

    toplevel = get_toplevel()
    if not toplevel:
        return {}

    plan_path = get_plan_path(toplevel=toplevel)
    plan = Plan.load(path=plan_path)
    if not plan.metadata:
        return {}

    return plan._to_dict()


async def archive() -> dict[str, Any]:
    from datetime import UTC, datetime
    from pathlib import Path

    from dev10x.hooks.task_plan_sync import (
        Plan,
        get_plan_path,
        get_toplevel,
    )

    toplevel = get_toplevel()
    if not toplevel:
        return {"error": "Not in a git repository"}

    plan_path = get_plan_path(toplevel=toplevel)
    if not plan_path.exists():
        return {"success": True, "message": "No plan file to archive"}

    plan = Plan.load(path=plan_path)
    archive_dir = Path(toplevel) / ".claude" / "session" / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    branch_slug = plan.metadata.get("branch", "unknown")
    branch_slug = branch_slug.replace("/", "-")[:50]
    archive_name = f"plan-{timestamp}-{branch_slug}.yaml"
    archive_path = archive_dir / archive_name

    plan.metadata["archived_at"] = datetime.now(UTC).isoformat()
    plan.save(path=archive_path)
    plan_path.unlink()
    return {"success": True, "archive_name": archive_name}
