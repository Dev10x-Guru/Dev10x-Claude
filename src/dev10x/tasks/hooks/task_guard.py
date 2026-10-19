"""PreToolUse guard for the empty-task-list invariant (GH-681 / GH-149).

An orchestrated session must never silently empty its task list: the
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

Scope (ADR-0034, GH-1556/GH-1557): the guard belongs to the tasks plugin.
A plan is guarded when its context sets ``guard_terminal_task`` — the
opt-in any orchestrator can write — or when a plugin listed in
``PLUGIN_TRIGGER_KEYS`` is enabled and the context carries one of that
plugin's keys (``work_on``/``routing_table`` for coding). Ad-hoc task
lists are never blocked, so the guard adds no friction outside the
workflows it protects.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from dev10x.core.plan_mirror import read_plan_mirror
from dev10x.core.plugin_enablement import is_plugin_enabled
from dev10x.domain.documents.plan import Plan, get_plan_path, get_toplevel
from dev10x.domain.events.hook_input import HookResult
from dev10x.hooks.hook_transport import emit

log = logging.getLogger(__name__)

GUARD_FLAG = "guard_terminal_task"
PLUGIN_TRIGGER_KEYS: dict[str, frozenset[str]] = {
    "coding": frozenset({"work_on", "routing_table"}),
}


def _override_present(*, tool_input: dict) -> bool:
    if os.environ.get("DEV10X_TASK_GUARD_OFF"):
        return True
    metadata = tool_input.get("metadata")
    return isinstance(metadata, dict) and metadata.get("supervisor_confirmed") is True


def _plan_context(*, plan: Plan) -> dict[str, Any]:
    context = plan.metadata.get("context", {})
    return context if isinstance(context, dict) else {}


def is_guarded_plan(*, plan: Plan, enabled_plugins: frozenset[str]) -> bool:
    context = _plan_context(plan=plan)
    if context.get(GUARD_FLAG):
        return True
    return any(
        plugin in enabled_plugins and not trigger_keys.isdisjoint(context)
        for plugin, trigger_keys in PLUGIN_TRIGGER_KEYS.items()
    )


def enabled_trigger_plugins(*, project_dir: Path | None) -> frozenset[str]:
    return frozenset(
        plugin
        for plugin in PLUGIN_TRIGGER_KEYS
        if is_plugin_enabled(key=plugin, project_dir=project_dir)
    )


def guard_decision(
    *,
    tool_input: dict,
    plan: Plan,
    enabled_plugins: frozenset[str],
) -> HookResult | None:
    """Return a ``HookResult`` to block the update, or ``None`` to allow it."""
    status = tool_input.get("status")
    task_id = tool_input.get("taskId")
    if not task_id:
        return None
    if not is_guarded_plan(plan=plan, enabled_plugins=enabled_plugins):
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
            f"'{violation.subject}' as {status}. An orchestrated session (dev10x:work-on, "
            f"or any plan whose context sets {GUARD_FLAG}) must keep at least one open "
            "task until the supervisor confirms the work is shippable (PR merged, CI "
            "green, no open review comments). If the supervisor has confirmed "
            "completion, re-issue TaskUpdate with metadata.supervisor_confirmed=true; "
            "otherwise add the next task before closing this one, or keep a 'Verify "
            "acceptance criteria' task open. (DEV10X_TASK_GUARD_OFF=1 disables this "
            "guard.)"
        )
    )


def cmd_hook() -> None:
    payload_str = sys.stdin.read()
    if not payload_str.strip():
        sys.exit(0)

    try:
        payload = json.loads(payload_str)
    except json.JSONDecodeError as exc:
        log.warning("task-guard: hook payload is not valid JSON; allowing: %s", exc)
        sys.exit(0)

    if not isinstance(payload, dict):
        log.warning(
            "task-guard: hook payload is not a JSON object (%s); allowing",
            type(payload).__name__,
        )
        sys.exit(0)

    if payload.get("tool_name") != "TaskUpdate":
        sys.exit(0)

    tool_input = payload.get("tool_input", {})
    if not isinstance(tool_input, dict):
        log.warning(
            "task-guard: tool_input is not a JSON object (%s); allowing",
            type(tool_input).__name__,
        )
        sys.exit(0)

    toplevel = get_toplevel()
    if not toplevel:
        log.warning("task-guard: no git toplevel for the current directory; allowing")
        sys.exit(0)

    plan = read_plan_mirror(path=get_plan_path(toplevel=toplevel)).to_plan()
    result = guard_decision(
        tool_input=tool_input,
        plan=plan,
        enabled_plugins=enabled_trigger_plugins(project_dir=Path(toplevel)),
    )
    if result is not None:
        emit(result)
    sys.exit(0)
