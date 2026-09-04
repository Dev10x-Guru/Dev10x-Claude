"""Every settings-file writer must consult the git-tracked guard (GH-1155).

The original defect was not a wrong guard — it was a guard with one
caller. `ensure_base` checked whether its target was a git-tracked
`settings.json`; `ensure_scripts`, `ensure_reads`, `update-paths` and
`promote-plan` did not, and one maintenance run took a tracked file from
2 committed rules to 1495 allow / 51 ask / 82 deny across 16 working
trees.

Behavioural tests cover the guard's own semantics and two of the
writers, but they cannot catch the regression that actually happened:
deleting the guard call from one writer leaves every behavioural test
green, because each test exercises a different function. So this asserts
the wiring structurally, over the AST — the same approach the repo
already uses for `test_no_module_scope_gitcontext.py` and
`test_cwd_enforcement.py`.

`seed_worktree` is deliberately absent. It writes into a worktree it has
just created, so its settings file cannot pre-exist as a tracked file
carrying unrelated committed content — the bug class does not transfer.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import dev10x.skills.permission as permission_pkg

_UPDATE_PATHS = Path(permission_pkg.__file__).parent / "update_paths.py"
_COMMANDS = Path(permission_pkg.__file__).resolve().parents[2] / "commands" / "permission.py"

_GUARD_NAMES = frozenset({"partition_writable", "_partition_writable"})

# Writers in update_paths.py that take a settings_files list and write it.
_GUARDED_WRITERS = (
    "ensure_base",
    "ensure_scripts",
    "ensure_user_skill_scripts",
    "ensure_reads",
    "ensure_workspace",
    "generalize",
)


def _function_node(*, source: Path, name: str) -> ast.FunctionDef:
    tree = ast.parse(source.read_text())
    matches = [
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert matches, f"{name} not found at module scope in {source.name}"
    return matches[0]


def _calls_the_guard(node: ast.AST) -> bool:
    return any(
        isinstance(call.func, ast.Name)
        and call.func.id in _GUARD_NAMES
        or isinstance(call.func, ast.Attribute)
        and call.func.attr in _GUARD_NAMES
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
    )


@pytest.mark.parametrize("writer", _GUARDED_WRITERS)
def test_writer_consults_the_git_tracked_guard(writer: str) -> None:
    node = _function_node(source=_UPDATE_PATHS, name=writer)
    assert _calls_the_guard(node), (
        f"{writer}() writes settings files without consulting the "
        "git-tracked guard. That is the GH-1155 regression: the guard "
        "existed but only one writer called it, so a tracked "
        "settings.json was rewritten anyway."
    )


@pytest.mark.parametrize("command", ["update_paths", "promote_plan"])
def test_cli_command_consults_the_git_tracked_guard(command: str) -> None:
    node = _function_node(source=_COMMANDS, name=command)
    assert _calls_the_guard(node), (
        f"the `{command}` CLI command writes settings files without "
        "consulting the git-tracked guard (GH-1155)."
    )


@pytest.mark.parametrize(
    "writer",
    [
        "ensure_scripts",
        "ensure_user_skill_scripts",
        "ensure_reads",
        "ensure_workspace",
        "generalize",
    ],
)
def test_writer_exposes_the_allow_tracked_escape_hatch(writer: str) -> None:
    node = _function_node(source=_UPDATE_PATHS, name=writer)
    names = {arg.arg for arg in node.args.kwonlyargs} | {arg.arg for arg in node.args.args}
    assert "allow_tracked" in names, (
        f"{writer}() guards against tracked files but offers no "
        "allow_tracked escape hatch, so a user who genuinely intends to "
        "commit their settings has no supported way through."
    )
