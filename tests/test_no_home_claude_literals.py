"""Lint test: no direct ``Path.home() / ".claude"`` construction (GH-829).

Every ``~/.claude`` path must be built through the ``ClaudeDir``
accessors in ``domain/claude_paths.py`` (or ``Dev10xConfigDir`` for the
XDG config home) so home resolution and the ``DEV10X_CLAUDE_HOME``
test/CI override live in exactly one place. A stray
``Path.home() / ".claude" / ...`` bypasses the override and re-scatters
home-dir resolution — the drift GH-575/GH-80 set out to end.

Scope: this gate flags only the direct home-relative anti-pattern —
a ``/``-join whose left side is a ``.home()`` call and whose right side
is the literal ``".claude"``. It deliberately does NOT flag:

* repo-relative / worktree-relative ``.claude`` paths
  (``toplevel / ".claude"``, ``Path(".claude")``) — a different
  concern that ``ClaudeDir`` (a home accessor) does not model;
* plugin-relative ``plugin_root / ".claude"`` rule paths;
* ``.claude`` in comments, docstrings, regexes, help text, or the
  unrelated ``.claude-plugin`` manifest directory.

Those are legitimate and out of ClaudeDir's home scope; the ratchet
targets the one construction that has a drop-in accessor replacement.
"""

from __future__ import annotations

import ast
from pathlib import Path

from dev10x.subprocess_utils import get_plugin_root

_ACCESSOR_MODULES = {"claude_paths.py", "dev10x_paths.py"}


def _src_root() -> Path:
    return get_plugin_root() / "src" / "dev10x"


def _is_home_call(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "home"
    )


def _is_claude_literal(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value == ".claude"


def _home_claude_joins(tree: ast.Module) -> list[int]:
    offenders: list[int] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Div)
            and _is_home_call(node.left)
            and _is_claude_literal(node.right)
        ):
            offenders.append(node.lineno)
    return offenders


def test_no_home_claude_literal_construction() -> None:
    offenders: list[str] = []
    for path in sorted(_src_root().rglob("*.py")):
        if path.name in _ACCESSOR_MODULES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for lineno in _home_claude_joins(tree):
            offenders.append(f"{path.relative_to(_src_root())}:{lineno}")

    assert not offenders, (
        "Build `~/.claude` paths via `ClaudeDir` accessors "
        '(dev10x.domain.claude_paths), never `Path.home() / ".claude"` '
        "directly — the accessor owns home resolution and the "
        "DEV10X_CLAUDE_HOME override (GH-829). Offenders:\n  - " + "\n  - ".join(offenders)
    )
