"""Task plan synchronizer — persists task state to a YAML plan file.

Triggered on TaskCreate and TaskUpdate. Maintains a per-project
plan file that survives context compaction and session restarts.

Plan file location:
    <git-toplevel>/.claude/session/plan.yaml
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dev10x.domain.file_locks import file_lock
from dev10x.domain.git_context import GitContext
from dev10x.domain.plan import Plan


def get_toplevel() -> str | None:
    # GH-979: Fresh GitContext per call so the MCP server (long-lived
    # process) sees the caller's effective CWD on every invocation
    # instead of caching the directory the first call happened to hit.
    return GitContext().toplevel


def get_plan_path(*, toplevel: str) -> Path:
    return Path(toplevel) / ".claude" / "session" / "plan.yaml"


def read_plan(*, plan_path: Path) -> dict[str, Any]:
    plan = Plan.load(path=plan_path)
    return plan._to_dict()


def cmd_set_context(*, args: list[str]) -> None:
    toplevel = get_toplevel()
    if not toplevel:
        print("Not in a git repository", file=sys.stderr)
        sys.exit(1)

    plan_path = get_plan_path(toplevel=toplevel)
    plan = Plan.load(path=plan_path)
    plan.ensure_metadata()

    for arg in args:
        if "=" not in arg:
            print(f"Invalid argument (expected K=V): {arg}", file=sys.stderr)
            sys.exit(1)
        key, value = arg.split("=", 1)
        plan.set_context(key=key, value=value)

    plan.save(path=plan_path)
    context = plan.metadata.get("context", {})
    print(f"Updated plan context: {list(context.keys())}")


def cmd_archive() -> None:
    toplevel = get_toplevel()
    if not toplevel:
        print("Not in a git repository", file=sys.stderr)
        sys.exit(1)

    plan_path = get_plan_path(toplevel=toplevel)
    if not plan_path.exists():
        print("No plan file to archive")
        sys.exit(0)

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
    print(f"Archived plan to {archive_path.name}")


def cmd_json_summary() -> None:
    toplevel = get_toplevel()
    if not toplevel:
        json.dump({}, sys.stdout)
        sys.exit(0)

    plan_path = get_plan_path(toplevel=toplevel)
    plan = Plan.load(path=plan_path)
    if not plan.metadata:
        json.dump({}, sys.stdout)
        sys.exit(0)

    json.dump(plan._to_dict(), sys.stdout, indent=2)


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

    tool_name = payload.get("tool_name", "")

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

        changed = False
        if tool_name == "TaskCreate":
            changed = plan.handle_task_create(
                tool_input=tool_input,
                tool_result=tool_result,
            )
        elif tool_name == "TaskUpdate":
            plan.handle_task_update(tool_input=tool_input)
            changed = True
        else:
            sys.exit(0)

        if is_new_plan and not changed:
            sys.exit(0)

        plan.check_all_completed()
        plan.save(path=plan_path)
