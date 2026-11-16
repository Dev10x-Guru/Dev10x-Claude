"""Register herdr's cli-server tools (GH-1984)."""

from __future__ import annotations

from types import ModuleType

from mcp.server.fastmcp import FastMCP

from dev10x.core.mcp.registry import import_tool_modules

TOOL_MODULES: tuple[str, ...] = ("dev10x.herdr.mcp.roster_tools",)


def register(server: FastMCP) -> tuple[ModuleType, ...]:
    return import_tool_modules(server=server, modules=TOOL_MODULES)
