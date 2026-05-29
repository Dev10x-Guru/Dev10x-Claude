"""Lint test: no module-scope `GitContext()` instantiation (GH-979 H11).

A `GitContext` constructed at module scope caches the toplevel from
whichever CWD the module was first imported in. Long-lived MCP server
processes then resolve every later call against that stale directory —
the root-cause class of GH-979. Construct a fresh `GitContext()` per
call (or `lambda: GitContext().toplevel`) instead.
"""

from __future__ import annotations

import ast
from pathlib import Path

from dev10x.subprocess_utils import get_plugin_root


def _src_root() -> Path:
    return get_plugin_root() / "src" / "dev10x"


def _is_gitcontext_call(value: ast.expr) -> bool:
    if not isinstance(value, ast.Call):
        return False
    func = value.func
    if isinstance(func, ast.Name):
        return func.id == "GitContext"
    if isinstance(func, ast.Attribute):
        return func.attr == "GitContext"
    return False


def _module_scope_gitcontext_assignments(tree: ast.Module) -> list[int]:
    offenders: list[int] = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and _is_gitcontext_call(node.value):
            offenders.append(node.lineno)
        elif (
            isinstance(node, ast.AnnAssign)
            and node.value is not None
            and _is_gitcontext_call(node.value)
        ):
            offenders.append(node.lineno)
    return offenders


def test_no_module_scope_gitcontext_singletons() -> None:
    offenders: list[str] = []
    for path in sorted(_src_root().rglob("*.py")):
        tree = ast.parse(path.read_text())
        for lineno in _module_scope_gitcontext_assignments(tree):
            offenders.append(f"{path.relative_to(_src_root())}:{lineno}")

    assert not offenders, (
        "Module-scope `GitContext()` caches the first-call CWD permanently "
        "across MCP invocations (GH-979 H11). Build a fresh GitContext() per "
        "call instead. Offenders:\n  - " + "\n  - ".join(offenders)
    )
