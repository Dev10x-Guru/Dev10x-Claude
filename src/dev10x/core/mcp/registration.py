"""Register core's cli-server tools, resources and prompts (GH-1549)."""

from __future__ import annotations

from types import ModuleType

from mcp.server.fastmcp import FastMCP

from dev10x.core.mcp.registry import import_tool_modules

TOOL_MODULES: tuple[str, ...] = (
    "dev10x.core.mcp.gate_tools",
    "dev10x.core.mcp.utility_tools",
    "dev10x.mcp.knowledge_prompts",
    "dev10x.mcp.knowledge_resources",
    "dev10x.mcp.roots_tools",
    "dev10x.mcp.sampling_tools",
    "dev10x.mcp.usage_tools",
)


def register(server: FastMCP) -> tuple[ModuleType, ...]:
    return import_tool_modules(server=server, modules=TOOL_MODULES)
