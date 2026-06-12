"""Plan transaction layer.

The IO/transaction boundary for a project's plan file. This layer
owns the concerns the `Plan` aggregate must not — git-toplevel
resolution, file locking, and removing the live plan file — and
delegates all name derivation, stamping, and persistence to `Plan`
(`Plan.archive_to`, `Plan.save`, `Plan.set_context`). It stays
separate from the aggregate deliberately (audit D8): folding this
IO into domain methods would couple the aggregate to the filesystem
layout and the lock primitive.

Both the CLI hook (`dev10x.hooks.task_plan_sync`) and the MCP
wrapper (`dev10x.plan`) delegate here, eliminating the previously
duplicated `archive()` block and inline imports.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from dev10x.domain.documents.plan import Plan, get_plan_path, get_toplevel
from dev10x.domain.file_locks import file_lock  # noqa: F401


class PlanServiceError(Exception):
    """Raised when a plan service operation cannot proceed."""


def set_plan_context(*, args: list[str]) -> list[str]:
    """Apply K=V context updates to the plan; return updated keys."""
    toplevel = get_toplevel()
    if not toplevel:
        raise PlanServiceError("Not in a git repository")

    plan_path = get_plan_path(toplevel=toplevel)
    with file_lock(plan_path):
        plan = Plan.load(path=plan_path)
        plan.ensure_metadata()

        for arg in args:
            if "=" not in arg:
                raise PlanServiceError(f"Invalid argument (expected K=V): {arg}")
            key, value = arg.split("=", 1)
            plan.set_context(key=key, value=value)

        plan.save(path=plan_path)
        return plan.context_keys()


def plan_summary() -> dict[str, Any]:
    """Return the plan as a YAML-shaped dict, or `{}` when not yet started."""
    toplevel = get_toplevel()
    if not toplevel:
        raise PlanServiceError("Not in a git repository")

    plan_path = get_plan_path(toplevel=toplevel)
    plan = Plan.load(path=plan_path)
    if plan.is_new:
        return {}
    return plan.to_dict()


def archive_plan() -> dict[str, Any]:
    """Move the active plan file into the session archive.

    Returns a dict describing the outcome: `{"archived": False}` when
    there is no plan to archive, or `{"archived": True, "archive_name": ...}`
    after a successful move. Callers translate this into a CLI message
    or MCP response payload.
    """
    toplevel = get_toplevel()
    if not toplevel:
        raise PlanServiceError("Not in a git repository")

    plan_path = get_plan_path(toplevel=toplevel)
    with file_lock(plan_path):
        if not plan_path.exists():
            return {"archived": False}

        plan = Plan.load(path=plan_path)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        archive_path = plan.archive_to(
            archive_dir=plan_path.parent / "archive",
            timestamp=timestamp,
        )
        plan_path.unlink()
        return {"archived": True, "archive_name": archive_path.name}
