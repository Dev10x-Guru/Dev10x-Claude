"""Lint test: MCP tool handlers with `cwd` parameter must bind it.

Every `@server.tool()`-decorated async function in `server_cli.py` that
accepts a `cwd: str | None` parameter must either:

1. Apply `@requires_cwd` (binds `cwd` to the effective-CWD ContextVar), or
2. Manually wrap its body with `with use_cwd(cwd):`.

Handlers that forget the binding silently fall back to the MCP server's
startup CWD — the root-cause class of GH-979.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from dev10x.subprocess_utils import get_plugin_root


def _server_cli_path() -> Path:
    return get_plugin_root() / "src" / "dev10x" / "mcp" / "server_cli.py"


def _is_server_tool(decorator: ast.expr) -> bool:
    if isinstance(decorator, ast.Call):
        decorator = decorator.func
    if isinstance(decorator, ast.Attribute):
        return decorator.attr == "tool"
    if isinstance(decorator, ast.Name):
        return decorator.id == "tool"
    return False


def _has_requires_cwd(node: ast.AsyncFunctionDef) -> bool:
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Name) and target.id == "requires_cwd":
            return True
        if isinstance(target, ast.Attribute) and target.attr == "requires_cwd":
            return True
    return False


def _accepts_cwd_kwarg(node: ast.AsyncFunctionDef) -> bool:
    all_args = [*node.args.args, *node.args.kwonlyargs]
    return any(arg.arg == "cwd" for arg in all_args)


def _body_uses_use_cwd(node: ast.AsyncFunctionDef) -> bool:
    for sub in ast.walk(node):
        if not isinstance(sub, ast.With):
            continue
        for item in sub.items:
            call = item.context_expr
            if not isinstance(call, ast.Call):
                continue
            target = call.func
            if isinstance(target, ast.Name) and target.id == "use_cwd":
                return True
            if isinstance(target, ast.Attribute) and target.attr == "use_cwd":
                return True
    return False


def _server_tool_handlers() -> list[ast.AsyncFunctionDef]:
    tree = ast.parse(_server_cli_path().read_text())
    handlers: list[ast.AsyncFunctionDef] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        if any(_is_server_tool(dec) for dec in node.decorator_list):
            handlers.append(node)
    return handlers


def test_server_cli_handlers_with_cwd_bind_it() -> None:
    offenders: list[str] = []
    for handler in _server_tool_handlers():
        if not _accepts_cwd_kwarg(handler):
            continue
        if _has_requires_cwd(handler) or _body_uses_use_cwd(handler):
            continue
        offenders.append(f"{handler.name} (line {handler.lineno})")

    assert not offenders, (
        "MCP handlers declare a `cwd` parameter but neither apply "
        "@requires_cwd nor wrap the body with `use_cwd(cwd)`. "
        "Without one of these, subprocess calls leak to the server's "
        "startup CWD (GH-979). Offenders:\n  - " + "\n  - ".join(offenders)
    )


@pytest.mark.asyncio
async def test_requires_cwd_binds_effective_cwd(tmp_path: Path) -> None:
    from dev10x.subprocess_utils import effective_cwd, requires_cwd

    captured: dict[str, str | None] = {}

    @requires_cwd
    async def handler(*, cwd: str | None = None) -> dict[str, str | None]:
        captured["bound"] = effective_cwd()
        return {"ok": "1"}

    await handler(cwd=str(tmp_path))
    assert captured["bound"] == str(tmp_path)


@pytest.mark.asyncio
async def test_requires_cwd_passes_through_when_cwd_none() -> None:
    from dev10x.subprocess_utils import effective_cwd, requires_cwd

    captured: dict[str, str | None] = {}

    @requires_cwd
    async def handler(*, cwd: str | None = None) -> None:
        captured["bound"] = effective_cwd()

    await handler(cwd=None)
    assert captured["bound"] is None
