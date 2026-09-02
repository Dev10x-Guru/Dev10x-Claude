"""Reject unknown tool parameters at the MCP boundary (GH-1122).

FastMCP builds a pydantic model per tool from the handler signature. That
model does not set ``extra="forbid"``, so pydantic's default
``extra="ignore"`` validates an unrecognised key away; and even if it did
not, ``ArgModelBase.model_dump_one_level`` rebuilds the handler kwargs by
iterating ``model_fields``, discarding the key a second time. Two
independent mechanisms drop it, and the handler returns success having
never seen it.

The exposure is worst where it is least visible. ``.claude/rules/mcp-tools.md``
documents the surface on ``develop``; sessions run the *installed* release.
An agent calling ``update_pr(milestone=…)`` against a plugin that predates
GH-1098 got a success payload and no milestone — and the natural conclusion
("GitHub rejected it") is wrong. Every wrapper gains that hazard the moment
its documented surface runs ahead of the released one.

This module inverts that: an unknown parameter fails loud, names itself,
and reports the running plugin version so a version-lag mismatch is
self-diagnosing. It is the inbound counterpart to ``to_wire()``'s
return-path ``isinstance`` assert (ADR-0009) — one seam covering every
registered tool, so no handler needs individual treatment.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server.fastmcp.utilities.func_metadata import FuncMetadata

from dev10x.domain.install_version import read_plugin_version

log = logging.getLogger(__name__)


class UnknownToolParameterError(ValueError):
    """Raised when a tool call carries a parameter the handler cannot accept."""


def _accepted_names(arg_model: type[Any]) -> set[str]:
    """Field names AND aliases — an alias is a legitimate inbound key."""
    accepted: set[str] = set()
    for field_name, field_info in arg_model.model_fields.items():
        accepted.add(field_name)
        alias = getattr(field_info, "alias", None)
        if alias:
            accepted.add(alias)
    return accepted


class StrictFuncMetadata(FuncMetadata):
    """``FuncMetadata`` that refuses unknown arguments instead of dropping them."""

    async def call_fn_with_arg_validation(
        self,
        fn: Callable[..., Any | Awaitable[Any]],
        fn_is_async: bool,
        arguments_to_validate: dict[str, Any],
        arguments_to_pass_directly: dict[str, Any] | None,
    ) -> Any:
        accepted = _accepted_names(self.arg_model)
        unknown = sorted(set(arguments_to_validate) - accepted)
        if unknown:
            raise UnknownToolParameterError(_unknown_parameter_message(unknown))
        return await super().call_fn_with_arg_validation(
            fn,
            fn_is_async,
            arguments_to_validate,
            arguments_to_pass_directly,
        )


def _unknown_parameter_message(unknown: list[str]) -> str:
    named = ", ".join(repr(name) for name in unknown)
    plural = "parameters" if len(unknown) > 1 else "parameter"
    version = read_plugin_version() or "unknown"
    return (
        f"unknown {plural} {named} — not accepted by this tool in plugin "
        f"version {version}. The parameter was NOT applied. If the docs "
        f"list it, the running plugin predates that feature; upgrade "
        f"rather than retrying."
    )


def enforce_strict_arguments(server: Any) -> list[str]:
    """Swap every registered tool's metadata for the strict variant.

    Call once after all tool modules have been imported — that is the only
    point at which the registry is complete. Returns the tool names that
    were converted, so a test can assert the pass actually reached them.

    ``_tool_manager`` is private FastMCP API. If it moves, this raises
    rather than silently enforcing nothing: a no-op here would restore the
    exact silent-drop behaviour the module exists to remove.
    """
    manager = getattr(server, "_tool_manager", None)
    if manager is None or not hasattr(manager, "list_tools"):
        raise RuntimeError(
            "FastMCP server exposes no `_tool_manager.list_tools()` — the "
            "strict-argument pass (GH-1122) cannot reach the registered "
            "tools. Unknown parameters would be silently dropped again."
        )

    converted: list[str] = []
    for tool in manager.list_tools():
        metadata = getattr(tool, "fn_metadata", None)
        if metadata is None or isinstance(metadata, StrictFuncMetadata):
            continue
        # `arg_model` holds a *type*, so normal validation is the wrong
        # tool for the copy — model_construct carries the fields across.
        tool.fn_metadata = StrictFuncMetadata.model_construct(
            **{name: getattr(metadata, name) for name in type(metadata).model_fields}
        )
        converted.append(tool.name)

    log.debug("strict-argument pass applied to %d tools", len(converted))
    return converted
