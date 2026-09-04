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

import pytest

from dev10x.subprocess_utils import get_plugin_root

_SRC = get_plugin_root() / "src" / "dev10x"

# Parsed once at import: the two trees are byte-identical across all 13
# parametrized cases, so parsing per case re-read ~27k lines of source for
# no test-semantic benefit — and the waste grows with every writer added.
_UPDATE_PATHS_TREE = ast.parse((_SRC / "skills" / "permission" / "update_paths.py").read_text())
_COMMANDS_TREE = ast.parse((_SRC / "commands" / "permission.py").read_text())

_GUARD_NAMES = frozenset({"partition_writable", "_partition_writable"})

# Functions that take `settings_files` but do NOT write them, so the guard
# does not apply. Named individually, and the direction matters: the writer
# list below is DERIVED from the source and merely filtered by this set, so a
# new writer nobody remembers to classify lands in the checked set and fails
# loudly. An opt-in list of writers-to-check would have the same
# forget-to-update failure this file exists to catch.
_NON_WRITERS = frozenset(
    {
        "partition_writable",  # the guard itself
        "_partition_writable",  # back-compat alias
        "find_settings_files",  # discovery, returns the list
        "catalog_gap",  # read-only gap report
        "_residual_gap_errors",  # read-only post-write assertion
        # Writes into a worktree it has just created, so its settings file
        # cannot pre-exist as a tracked file holding unrelated committed
        # content — the bug class does not transfer (GH-1155).
        "seed_worktree",
    }
)

# `ensure_base` predates the escape hatch and plain-skips rather than
# redirecting, so it alone carries no `allow_tracked` parameter.
_WITHOUT_ESCAPE_HATCH = frozenset({"ensure_base"})


def _takes_settings_files(node: ast.FunctionDef) -> bool:
    args = node.args
    return "settings_files" in {
        arg.arg for arg in (*args.args, *args.kwonlyargs, *args.posonlyargs)
    }


def _derive_writers(tree: ast.Module) -> tuple[str, ...]:
    return tuple(
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and _takes_settings_files(node)
        and node.name not in _NON_WRITERS
    )


def _function_node(*, tree: ast.Module, name: str) -> ast.FunctionDef:
    matches = [
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert matches, f"{name} not found at module scope"
    return matches[0]


def _call_target_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _calls_the_guard(node: ast.AST) -> bool:
    return any(
        _call_target_name(call) in _GUARD_NAMES
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
    )


_GUARDED_WRITERS = _derive_writers(_UPDATE_PATHS_TREE)
_WRITERS_WITH_ALLOW_TRACKED = tuple(
    writer for writer in _GUARDED_WRITERS if writer not in _WITHOUT_ESCAPE_HATCH
)


def test_derivation_found_the_known_writers() -> None:
    assert set(_GUARDED_WRITERS) >= {
        "ensure_base",
        "ensure_scripts",
        "ensure_user_skill_scripts",
        "ensure_reads",
        "ensure_workspace",
        "generalize",
    }


@pytest.mark.parametrize("writer", _GUARDED_WRITERS)
def test_writer_consults_the_git_tracked_guard(writer: str) -> None:
    node = _function_node(tree=_UPDATE_PATHS_TREE, name=writer)
    assert _calls_the_guard(node), (
        f"{writer}() writes settings files without consulting the "
        "git-tracked guard. That is the GH-1155 regression: the guard "
        "existed but only one writer called it, so a tracked "
        "settings.json was rewritten anyway."
    )


@pytest.mark.parametrize("command", ["update_paths", "promote_plan"])
def test_cli_command_consults_the_git_tracked_guard(command: str) -> None:
    node = _function_node(tree=_COMMANDS_TREE, name=command)
    assert _calls_the_guard(node), (
        f"the `{command}` CLI command writes settings files without "
        "consulting the git-tracked guard (GH-1155)."
    )


@pytest.mark.parametrize("writer", _WRITERS_WITH_ALLOW_TRACKED)
def test_writer_exposes_the_allow_tracked_escape_hatch(writer: str) -> None:
    node = _function_node(tree=_UPDATE_PATHS_TREE, name=writer)
    names = {arg.arg for arg in node.args.kwonlyargs} | {arg.arg for arg in node.args.args}
    assert "allow_tracked" in names, (
        f"{writer}() guards against tracked files but offers no "
        "allow_tracked escape hatch, so a user who genuinely intends to "
        "commit their settings has no supported way through."
    )
