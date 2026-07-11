"""PreToolUse guard for the empty-task-list invariant (GH-681 / GH-149).

A ``Dev10x:work-on`` session must never silently empty its task list: the
terminal "Verify acceptance criteria" task stays open until the supervisor
confirms the work is shippable. This guard refuses a ``TaskUpdate`` that
would mark the terminal task — or the last remaining open task —
``completed``/``deleted``, converting a silent auto-completion into a
deliberate, auditable step.

The block is overridable two ways:

* ``metadata.supervisor_confirmed=true`` on the ``TaskUpdate`` — the
  explicit sign-off the completion gate records once the supervisor picks
  "Work complete".
* ``DEV10X_TASK_GUARD_OFF`` in the environment — a global kill switch.

Scope: only work-on-orchestrated plans are guarded, detected via the
``work_on``/``routing_table`` context keys ``plan_sync_set_context``
writes. Ad-hoc task lists (no such context) are never blocked, so the
guard adds no friction outside the workflow it protects.
"""

from __future__ import annotations

import json
import os
import sys

from dev10x.domain.documents.plan import Plan, get_plan_path, get_toplevel
from dev10x.domain.events.hook_input import HookResult
from dev10x.hooks.hook_transport import emit


def _override_present(*, tool_input: dict) -> bool:
    if os.environ.get("DEV10X_TASK_GUARD_OFF"):
        return True
    metadata = tool_input.get("metadata")
    return isinstance(metadata, dict) and metadata.get("supervisor_confirmed") is True


def _is_work_on_plan(*, plan: Plan) -> bool:
    context = plan.metadata.get("context", {})
    return isinstance(context, dict) and ("work_on" in context or "routing_table" in context)


def guard_decision(*, tool_input: dict, plan: Plan) -> HookResult | None:
    """Return a ``HookResult`` to block the update, or ``None`` to allow it."""
    status = tool_input.get("status")
    task_id = tool_input.get("taskId")
    if not task_id:
        return None
    if not _is_work_on_plan(plan=plan):
        return None
    if _override_present(tool_input=tool_input):
        return None

    violation = plan.would_violate_terminal_task_invariant(task_id=task_id, closing_status=status)
    if violation is None:
        return None

    label = "terminal Verify-AC task" if violation.is_terminal else "last open task"
    return HookResult(
        message=(
            f"Empty-task-list invariant (GH-149): refusing to mark the {label} "
            f"'{violation.subject}' as {status}. A Dev10x:work-on session must keep "
            "at least one open task until the supervisor confirms the work is "
            "shippable (PR merged, CI green, no open review comments). If the "
            "supervisor has confirmed completion, re-issue TaskUpdate with "
            "metadata.supervisor_confirmed=true; otherwise add the next task "
            "before closing this one, or keep a 'Verify acceptance criteria' "
            "task open. (DEV10X_TASK_GUARD_OFF=1 disables this guard.)"
        )
    )


def cmd_hook() -> None:
    payload_str = sys.stdin.read()
    if not payload_str.strip():
        sys.exit(0)

    try:
        payload = json.loads(payload_str)
    except json.JSONDecodeError:
        sys.exit(0)

    if payload.get("tool_name") != "TaskUpdate":
        sys.exit(0)

    tool_input = payload.get("tool_input", {})
    if not isinstance(tool_input, dict):
        sys.exit(0)

    toplevel = get_toplevel()
    if not toplevel:
        sys.exit(0)

    plan = Plan.load(path=get_plan_path(toplevel=toplevel))
    result = guard_decision(tool_input=tool_input, plan=plan)
    if result is not None:
        emit(result)
    sys.exit(0)
