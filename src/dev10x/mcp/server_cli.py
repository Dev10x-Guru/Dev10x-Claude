"""MCP server registration for the Dev10x CLI server.

Tool handlers live in each plugin namespace's ``mcp/`` package
(ADR-0034), and every namespace exposes
``dev10x.<namespace>.mcp.registration.register(server)`` (GH-1549):

  - core    — gate, utility (mktmp, preamble, permission, upgrade),
              knowledge resources/prompts, roots, sampling, usage
  - coding  — git, GitHub, monitor, release, test-runner handlers
  - comm    — Slack thread heuristics
  - tasks   — plan-sync and task-index handlers
  - teach   — session audit and skill-index handlers

This module is the composition root: it iterates ``CLI_NAMESPACES``
instead of star-importing every tool module. Tool functions stay
reachable as attributes (``server_cli.mktmp``) through ``__getattr__``,
and ``server`` is re-exported for ``from dev10x.mcp.server_cli import
server`` callers.
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any, Literal, cast

from mcp.server.fastmcp import FastMCP

from dev10x.mcp._app import server
from dev10x.mcp.strict_args import enforce_strict_arguments

CLI_NAMESPACES: tuple[str, ...] = ("core", "coding", "comm", "tasks", "teach")


def register_namespaces(
    *,
    server: FastMCP,
    namespaces: tuple[str, ...] = CLI_NAMESPACES,
) -> tuple[ModuleType, ...]:
    registered: list[ModuleType] = []
    for namespace in namespaces:
        registration = importlib.import_module(f"dev10x.{namespace}.mcp.registration")
        registered.extend(registration.register(server))
    return tuple(registered)


TOOL_MODULES = register_namespaces(server=server)

# GH-1122: unknown kwargs are dropped twice over by FastMCP's generated
# arg model, so a call naming a parameter this release does not have
# returns success having changed nothing. Run AFTER every namespace has
# registered — that is the only point where the registry is complete.
enforce_strict_arguments(server)


def __getattr__(name: str) -> Any:
    for module in TOOL_MODULES:
        if name in vars(module):
            return vars(module)[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def main() -> None:
    from dev10x.mcp.wiring import select_transport_with_daemon_fallback

    # The fallback returns one of FastMCP's documented transports; cast so
    # the Literal-typed `run(transport=...)` parameter resolves (GH-619).
    transport = cast(
        Literal["stdio", "sse", "streamable-http"],
        select_transport_with_daemon_fallback(),
    )
    server.run(transport=transport)
