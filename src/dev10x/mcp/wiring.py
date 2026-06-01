"""Claude Code daemon wiring with STDIO fallback (GH-338).

Provides the transport-selection logic that lets Claude Code connect to
the long-lived Dev10x MCP daemon when it is running, and falls back to
a fresh per-session STDIO server when the daemon is absent or unhealthy.

Architecture
------------
Claude Code's ``plugin.json`` declares a ``command``-based MCP server
entry, which always spawns the server via STDIO.  This module sits
inside that spawned process and decides *how* the server actually
serves:

1. **Daemon healthy** — ``select_transport_with_daemon_fallback()``
   returns ``"streamable-http"``.  The server attaches to the daemon's
   already-open HTTP port and serves subsequent requests there.
   Claude Code's STDIO pipe is not used after the handshake.

   .. note::
       This path requires the daemon to have been started separately
       (e.g. ``dev10x daemon start``).  See ``daemon.py`` for the
       lifecycle API.

2. **Daemon absent / unhealthy** — returns ``"stdio"``.  The server
   runs in standard STDIO mode, identical to the pre-daemon behaviour.
   No external daemon is required.

Environment variables
---------------------
FASTMCP_HOST
    Hostname or IP for the daemon's HTTP endpoint.
    Defaults to ``127.0.0.1``.

FASTMCP_PORT
    TCP port for the daemon's HTTP endpoint.  Defaults to ``8000``.

DEV10X_MCP_DAEMON_PATH
    URL path suffix appended after ``host:port``.  Defaults to
    ``/mcp``.  Override only when the daemon is behind a reverse proxy
    that rewrites the path.

DEV10X_MCP_TRANSPORT
    When set to any value *other than* ``"auto"`` (or when absent),
    ``select_transport_with_daemon_fallback()`` delegates to the plain
    :func:`~dev10x.mcp.transport.select_transport` function so that
    explicit overrides are always honoured.  Set to ``"auto"`` to
    enable automatic daemon detection.

Usage example
-------------
In ``server_cli.py``::

    def main() -> None:
        from dev10x.mcp.wiring import select_transport_with_daemon_fallback
        server.run(transport=select_transport_with_daemon_fallback())
"""

from __future__ import annotations

import logging
import os

from dev10x.mcp.daemon import is_daemon_healthy
from dev10x.mcp.transport import select_transport

log = logging.getLogger(__name__)

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8000
_DEFAULT_PATH = "/mcp"


def daemon_base_url() -> str:
    """Return the daemon's ``http://host:port`` base URL.

    Reads ``FASTMCP_HOST`` and ``FASTMCP_PORT`` (FastMCP's own env
    vars).  Falls back to ``127.0.0.1:8000`` when the variables are
    absent or empty.

    Returns:
        A string like ``"http://127.0.0.1:8000"``.
    """
    host = os.environ.get("FASTMCP_HOST", "").strip() or _DEFAULT_HOST
    port_raw = os.environ.get("FASTMCP_PORT", "").strip()
    try:
        port = int(port_raw) if port_raw else _DEFAULT_PORT
    except ValueError:
        log.warning("Invalid FASTMCP_PORT=%r, using default %d", port_raw, _DEFAULT_PORT)
        port = _DEFAULT_PORT
    return f"http://{host}:{port}"


def daemon_mcp_url() -> str:
    """Return the full URL of the daemon's MCP endpoint.

    Combines :func:`daemon_base_url` with the path suffix read from
    ``DEV10X_MCP_DAEMON_PATH`` (default ``/mcp``).

    Returns:
        A string like ``"http://127.0.0.1:8000/mcp"``.
    """
    path = os.environ.get("DEV10X_MCP_DAEMON_PATH", "").strip() or _DEFAULT_PATH
    if not path.startswith("/"):
        path = "/" + path
    return daemon_base_url() + path


def select_transport_with_daemon_fallback() -> str:
    """Select MCP transport, preferring the daemon over STDIO.

    Decision matrix
    ~~~~~~~~~~~~~~~

    +------------------------------+-------------------------------------+
    | Condition                    | Result                              |
    +==============================+=====================================+
    | ``DEV10X_MCP_TRANSPORT``     | delegate to                         |
    | is set to anything other     | ``transport.select_transport()``    |
    | than ``"auto"``              | (explicit override wins)            |
    +------------------------------+-------------------------------------+
    | ``DEV10X_MCP_TRANSPORT``     | run health check:                   |
    | is ``"auto"`` or absent      | healthy → ``"streamable-http"``     |
    |                              | unhealthy → ``"stdio"``             |
    +------------------------------+-------------------------------------+

    When the env var is absent the function behaves as if it were set
    to ``"auto"``, which means daemon detection runs by default.  Set
    the variable to ``"stdio"`` explicitly to skip detection entirely.

    Returns:
        One of ``"stdio"``, ``"streamable-http"``, or ``"sse"``.

    Raises:
        ValueError: When ``DEV10X_MCP_TRANSPORT`` is set to an
            unrecognised non-``"auto"`` value (delegated from
            :func:`~dev10x.mcp.transport.select_transport`).
    """
    raw = os.environ.get("DEV10X_MCP_TRANSPORT", "").strip().lower()

    if raw and raw != "auto":
        # Explicit override — delegate to the strict transport selector.
        return select_transport()

    # "auto" mode or env var absent: attempt daemon detection.
    if is_daemon_healthy():
        log.info(
            "Daemon is healthy at %s — using streamable-http transport",
            daemon_mcp_url(),
        )
        return "streamable-http"

    log.info("Daemon not available — falling back to stdio transport")
    return "stdio"
