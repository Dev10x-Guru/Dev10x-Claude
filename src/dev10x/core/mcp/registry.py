"""Per-namespace MCP tool registration (ADR-0034 Stage A2, GH-1549).

Each namespace that ships cli-server tools exposes
``dev10x.<namespace>.mcp.registration.register(server)``; server_cli
iterates its namespace list instead of star-importing every tool module.

Tool modules still bind their handlers to the shared app at import time
(``@server.tool()`` / ``@mcp_tool``), so registering means importing them.
``import_tool_modules`` therefore refuses any server other than the shared
app: a caller passing a fresh server would otherwise get a silent no-op.
Binding a namespace to a server of its own is B9's job, not Stage A's.
"""

from __future__ import annotations

import importlib
from types import ModuleType

from mcp.server.fastmcp import FastMCP

from dev10x.core.mcp._app import server as cli_app


class ForeignServerError(ValueError):
    def __init__(self, *, server: FastMCP) -> None:
        super().__init__(
            f"MCP tool modules register on the shared Dev10x-cli app, not on "
            f"{server.name!r}; pass dev10x.core.mcp._app.server (ADR-0034 B9 "
            f"owns per-plugin servers)."
        )


def import_tool_modules(
    *,
    server: FastMCP,
    modules: tuple[str, ...],
) -> tuple[ModuleType, ...]:
    if server is not cli_app:
        raise ForeignServerError(server=server)
    return tuple(importlib.import_module(name) for name in modules)


__all__ = ["ForeignServerError", "import_tool_modules"]
