"""Lint test: no blocking git call inside an MCP coroutine (GH-1457).

`GitContext`'s accessors shell out to git. Read from inside an
``async def`` they block the daemon's single event loop for the whole
call, so one wedged git stalls every worktree sharing the process —
GH-1412's timeout bounds that window but does not free the loop.
Wrap the call in ``asyncio.to_thread`` instead.
"""

from __future__ import annotations

import ast
from pathlib import Path

from dev10x.subprocess_utils import get_plugin_root

#: Accessors that shell out to git.
_BLOCKING_ATTRS = frozenset({"toplevel", "branch", "common_dir"})

#: Sync entry points that reach a blocking accessor underneath. A new
#: one belongs here the moment a coroutine can reach it; the list is a
#: floor, not a proof, and the module docstring says why.
_BLOCKING_CALLS = frozenset(
    {
        "preset_pin_status",
        "pin_preset",
        "resolve_repo_identity",
        "tracker_status",
        "pin_tracker",
        "ide_status",
        "pin_ide",
        "pin_supervisor_review",
        "_read_supervisor_review",
        "_computed_session_stale",
        "_current_branch",
    }
)

_SCANNED = ("mcp", "github")


def _src_root() -> Path:
    return get_plugin_root() / "src" / "dev10x"


def _is_to_thread(node: ast.expr) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr == "to_thread"
    return isinstance(func, ast.Name) and func.id == "to_thread"


def _is_gitcontext_call(node: ast.expr) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "GitContext"
    return isinstance(func, ast.Attribute) and func.attr == "GitContext"


def _called_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    if isinstance(node.func, ast.Name):
        return node.func.id
    return None


def _offenders_in(body: list[ast.stmt]) -> list[tuple[int, str]]:
    """Blocking reads reachable without crossing an ``asyncio.to_thread``."""
    found: list[tuple[int, str]] = []
    stack: list[ast.AST] = list(body)
    while stack:
        node = stack.pop()
        # A to_thread call is the fix — everything under it already runs
        # off-loop, so do not descend into its arguments.
        if isinstance(node, ast.Call) and _is_to_thread(node):
            continue
        # Only a read off a GitContext(...) instance. `self.toplevel` on a
        # query dataclass is a resolved string, not a subprocess.
        if (
            isinstance(node, ast.Attribute)
            and node.attr in _BLOCKING_ATTRS
            and _is_gitcontext_call(node.value)
        ):
            found.append((node.lineno, f"GitContext().{node.attr}"))
        if isinstance(node, ast.Call):
            name = _called_name(node)
            if name in _BLOCKING_CALLS:
                found.append((node.lineno, f"{name}()"))
        stack.extend(ast.iter_child_nodes(node))
    return found


def test_no_blocking_git_call_inside_a_coroutine() -> None:
    offenders: list[str] = []
    for package in _SCANNED:
        for path in sorted((_src_root() / package).rglob("*.py")):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.AsyncFunctionDef):
                    continue
                for lineno, what in _offenders_in(node.body):
                    offenders.append(
                        f"{path.relative_to(_src_root())}:{lineno} in async {node.name}() — {what}"
                    )

    assert not offenders, (
        "A blocking git call inside a coroutine stalls the MCP daemon's "
        "event loop for every worktree sharing it (GH-1457). Wrap it in "
        "`await asyncio.to_thread(...)`. Offenders:\n  - " + "\n  - ".join(sorted(offenders))
    )
