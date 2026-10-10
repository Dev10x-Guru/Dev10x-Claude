"""Transport selection for Dev10x MCP servers.

STDIO is the default and keeps existing Claude Code wiring unchanged.
HTTP transports are opt-in via the DEV10X_MCP_TRANSPORT environment
variable — required for daemon mode (GH-336 and beyond).

Environment variables
---------------------
DEV10X_MCP_TRANSPORT
    Transport to use.  Accepted values (case-insensitive):

    * ``stdio``            — default; standard input/output (Claude Code)
    * ``streamable-http``  — StreamableHTTP over HTTP (daemon mode)
    * ``sse``              — Server-Sent Events over HTTP (legacy HTTP)

    Any other value raises ``ValueError`` at server start-up so
    misconfigured deployments fail loudly instead of silently falling
    back to STDIO.

FASTMCP_HOST / FASTMCP_PORT
    Host and port for HTTP transports.  These are FastMCP's own env
    vars (prefix ``FASTMCP_``) and are read directly by FastMCP.
    Defaults: ``127.0.0.1`` / ``8000``.

Example — run over StreamableHTTP on all interfaces, port 9000::

    DEV10X_MCP_TRANSPORT=streamable-http \\
    FASTMCP_HOST=0.0.0.0 \\
    FASTMCP_PORT=9000 \\
        ./servers/cli_server.py
"""

from __future__ import annotations

import os
from typing import Literal

_VALID_TRANSPORTS = frozenset({"stdio", "streamable-http", "sse"})

TransportLiteral = Literal["stdio", "streamable-http", "sse"]


def select_transport() -> TransportLiteral:
    """Return the transport name to pass to ``FastMCP.run()``.

    Reads ``DEV10X_MCP_TRANSPORT`` (case-insensitive).  Defaults to
    ``"stdio"`` when the variable is absent or empty.

    Raises:
        ValueError: When the variable is set to an unrecognised value.
    """
    raw = os.environ.get("DEV10X_MCP_TRANSPORT", "").strip().lower()
    if not raw:
        return "stdio"
    if raw not in _VALID_TRANSPORTS:
        raise ValueError(
            f"DEV10X_MCP_TRANSPORT={raw!r} is not valid. "
            f"Accepted values: {', '.join(sorted(_VALID_TRANSPORTS))}."
        )
    return raw  # type: ignore[return-value]
