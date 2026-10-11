"""MCP server registration for the Dev10x DB server.

All @server.tool() registrations live here so servers/db_server.py
becomes a thin 3-line uv shim. Tool handlers use lazy imports to
defer domain module loading until each tool is called.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from dev10x.domain.common.result import to_wire

server = FastMCP(name="Dev10x-db")


@server.tool()
async def query(
    database: str,
    sql: str,
) -> dict:
    """Execute a read-only SQL query against a database.

    Args:
        database: Database alias (pp, pos, ps, bp, backend, bs)
        sql: SELECT statement (write operations are blocked)

    Returns:
        Dictionary with keys: columns (list), rows (list of tuples), row_count (int)
    """
    from dev10x import db as db_tools

    return to_wire(db_tools.query(database=database, sql=sql))


def main() -> None:
    from dev10x.mcp.transport import select_transport

    server.run(transport=select_transport())
