"""Shared FastMCP application instance for the Dev10x CLI server.

Split out of server_cli.py (GH-243/A6) so per-domain tool modules
register against one server without a circular import.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

server = FastMCP(name="Dev10x-cli")
