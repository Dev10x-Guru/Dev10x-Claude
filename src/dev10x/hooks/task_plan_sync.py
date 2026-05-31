"""Task plan synchronizer — CLI entry points for plan operations.

Triggered on TaskCreate and TaskUpdate (via `cmd_hook`) or invoked
directly from `dev10x hook plan ...` commands. The mutation logic
lives in `dev10x.plan.service`; this module is the thin CLI adapter
that handles stdin parsing, locking, and stdout/exit-code shaping.

Plan file location:
    <git-toplevel>/.claude/session/plan.yaml
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dev10x.domain.documents.plan import Plan, get_plan_path, get_toplevel
from dev10x.domain.file_locks import file_lock
from dev10x.plan.service import (
    PlanServiceError,
    archive_plan,
    plan_summary,
    set_plan_context,
)


def read_plan(*, plan_path: Path) -> dict[str, Any]:
    """Load plan YAML into a dict. Consumed by `dev10x.hooks.session`."""
    return Plan.load(path=plan_path).to_dict()


def cmd_set_context(*, args: list[str]) -> None:
    try:
        updated = set_plan_context(args=args)
    except PlanServiceError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    print(f"Updated plan context: {updated}")


def cmd_archive() -> None:
    try:
        result = archive_plan()
    except PlanServiceError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    if not result["archived"]:
        print("No plan file to archive")
        sys.exit(0)
    print(f"Archived plan to {result['archive_name']}")


def cmd_json_summary() -> None:
    try:
        summary = plan_summary()
    except PlanServiceError:
        json.dump({}, sys.stdout)
        sys.exit(0)

    if not summary:
        json.dump({}, sys.stdout)
        sys.exit(0)

    json.dump(summary, sys.stdout, indent=2)


def _apply_task_create(*, plan: Plan, tool_input: dict[str, Any], tool_result: Any) -> bool:
    return plan.handle_task_create(tool_input=tool_input, tool_result=tool_result)


def _apply_task_update(*, plan: Plan, tool_input: dict[str, Any], tool_result: Any) -> bool:
    plan.handle_task_update(tool_input=tool_input)
    return True


TOOL_HANDLERS: dict[str, Callable[..., bool]] = {
    "TaskCreate": _apply_task_create,
    "TaskUpdate": _apply_task_update,
}


def cmd_hook() -> None:
    payload_str = sys.stdin.read()
    if not payload_str.strip():
        sys.exit(0)

    try:
        payload: dict[str, Any] = json.loads(payload_str)
    except json.JSONDecodeError:
        sys.exit(0)

    tool_input = payload.get("tool_input", {})
    tool_result = payload.get("tool_result", "")
    if isinstance(tool_result, dict):
        tool_result = tool_result.get("content", str(tool_result))

    handler = TOOL_HANDLERS.get(payload.get("tool_name", ""))
    if handler is None:
        sys.exit(0)

    toplevel = get_toplevel()
    if not toplevel:
        sys.exit(0)

    plan_path = get_plan_path(toplevel=toplevel)
    # Lock spans the full load→mutate→save cycle: without it, two
    # concurrent TaskCreate hooks both read the same baseline plan
    # and the second save clobbers the first task entry.
    with file_lock(plan_path):
        plan = Plan.load(path=plan_path)
        is_new_plan = plan.is_new
        plan.ensure_metadata()

        changed = handler(plan=plan, tool_input=tool_input, tool_result=tool_result)

        if is_new_plan and not changed:
            sys.exit(0)

        plan.check_all_completed()
        plan.save(path=plan_path)
