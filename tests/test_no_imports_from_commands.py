"""Lint test: nothing outside ``dev10x.commands`` imports from it (GH-1444).

``commands/`` is the CLI layer — the outermost ring. A module in
``github/``, ``mcp/``, ``hooks/`` or ``domain/`` that imports it drags
Click and every CLI concern into callers that never asked for them,
and inverts the dependency direction the ADRs describe.
"""

from __future__ import annotations

import ast
from pathlib import Path

from dev10x.subprocess_utils import get_plugin_root

COMMANDS_PACKAGE = "dev10x.commands"


def _src_root() -> Path:
    return get_plugin_root() / "src" / "dev10x"


def _imported_modules(tree: ast.Module) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.append((node.lineno, node.module))
    return found


def _is_commands_module(name: str) -> bool:
    return name == COMMANDS_PACKAGE or name.startswith(f"{COMMANDS_PACKAGE}.")


def test_no_module_outside_commands_imports_commands() -> None:
    commands_dir = _src_root() / "commands"
    offenders: list[str] = []
    for path in sorted(_src_root().rglob("*.py")):
        if commands_dir in path.parents:
            continue
        tree = ast.parse(path.read_text())
        for lineno, module in _imported_modules(tree):
            if _is_commands_module(module):
                offenders.append(f"{path.relative_to(_src_root())}:{lineno} -> {module}")

    assert not offenders, (
        "Only the CLI layer may import dev10x.commands (GH-1444). Move the "
        "shared code into a lower layer instead. Offenders:\n  - " + "\n  - ".join(offenders)
    )


def test_detector_flags_a_commands_import() -> None:
    tree = ast.parse("from dev10x.commands.github_app import cli\nimport dev10x.commands\n")

    flagged = [module for _, module in _imported_modules(tree) if _is_commands_module(module)]

    assert flagged == ["dev10x.commands.github_app", "dev10x.commands"]


def test_detector_ignores_a_lookalike_package() -> None:
    tree = ast.parse("from dev10x.commandset import x\n")

    flagged = [module for _, module in _imported_modules(tree) if _is_commands_module(module)]

    assert flagged == []
