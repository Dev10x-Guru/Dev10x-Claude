"""McpToolName value object — canonical ``mcp__<server>__<tool>`` identity.

MCP tool identifiers were understood only implicitly: detection via
``startswith("mcp__")`` at five call sites, two incompatible compiled
regexes (``validators/mcp_prefix.py``, ``skills/permission/enumerate_mcp.py``),
and ad-hoc structural splits to recover the ``(server, tool)`` parts
(audit finding GH-508 — 2026-06-10).

This object is the single authoritative parse of an MCP tool name. The
predicates intentionally cover three distinct shapes:

* :meth:`is_mcp` — loose ``mcp__`` sentinel, replacing the ``startswith``
  sites.
* :meth:`is_command_token` — a fully-formed ``mcp__<server>__<tool>``
  appearing as the leading token of a Bash command (the anti-pattern the
  ``mcp-prefix`` validator blocks).
* :meth:`is_wildcard` — a glob-shaped rule (``mcp__<something>*``) that
  Claude Code's permission engine silently fails to expand.

The narrower ``mcp__plugin_<x>_*`` "nonfunctional Dev10x wildcard" used by
``update_paths`` is a different, plugin-specific concern and is left where
it lives.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MCP_PREFIX = "mcp__"
TOOL_NAME_PATTERN = r"mcp__[A-Za-z0-9_]+__[A-Za-z0-9_]+"
WILDCARD_PATTERN = r"mcp__[A-Za-z0-9_]+\*"

_COMMAND_TOKEN_RE = re.compile(rf"^{TOOL_NAME_PATTERN}")
_FULL_RE = re.compile(rf"^{TOOL_NAME_PATTERN}$")
_WILDCARD_RE = re.compile(rf"^{WILDCARD_PATTERN}$")


@dataclass(frozen=True)
class McpToolName:
    server: str
    tool: str

    def __str__(self) -> str:
        return f"{MCP_PREFIX}{self.server}__{self.tool}"

    @property
    def prefix(self) -> str:
        return f"{MCP_PREFIX}{self.server}__"

    @classmethod
    def is_mcp(cls, value: str) -> bool:
        """Loose sentinel: does ``value`` name an MCP tool at all?"""
        return isinstance(value, str) and value.startswith(MCP_PREFIX)

    @classmethod
    def is_command_token(cls, value: str) -> bool:
        """True when ``value`` begins with a full ``mcp__<server>__<tool>``.

        Used to detect an MCP identifier pasted as the leading token of a
        Bash command. A prefix (not full) match — trailing shell tokens
        after the identifier are expected.
        """
        return bool(_COMMAND_TOKEN_RE.match(value))

    @classmethod
    def is_wildcard(cls, value: str) -> bool:
        """True for a glob-shaped rule such as ``mcp__plugin_Dev10x_*``."""
        return bool(_WILDCARD_RE.match(value))

    @classmethod
    def parse(cls, value: str) -> McpToolName:
        if not isinstance(value, str) or not _FULL_RE.match(value):
            msg = f"Invalid MCP tool name: {value!r}. Expected 'mcp__<server>__<tool>'."
            raise ValueError(msg)
        parts = value.split("__")
        return cls(server="__".join(parts[1:-1]), tool=parts[-1])

    @classmethod
    def try_parse(cls, value: str) -> McpToolName | None:
        try:
            return cls.parse(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def prefix_of(cls, value: str) -> str | None:
        """Return the ``mcp__<server>__`` prefix of any MCP identifier.

        Structural only — accepts wildcard tools (``mcp__x__*``) that
        :meth:`parse` rejects. Returns ``None`` when ``value`` has fewer
        than three ``__``-delimited segments.
        """
        parts = value.split("__")
        if len(parts) < 3:
            return None
        return "__".join(parts[:-1]) + "__"
