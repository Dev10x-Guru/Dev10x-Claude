"""MCP server registration for the Dev10x DB server.

All @server.tool() registrations live here so servers/db_server.py
becomes a thin 3-line uv shim. Tool handlers use lazy imports to
defer domain module loading until each tool is called.
"""

from __future__ import annotations

import asyncio

from mcp.server.fastmcp import FastMCP

from dev10x.core.domain.common.result import to_wire

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


@server.tool()
async def bq_query(
    sql: str,
    project_id: str | None = None,
    location: str | None = None,
    max_rows: int = 100,
    maximum_bytes_billed: int = 10 * 1024**3,
    dry_run: bool = False,
) -> dict:
    """Run one read-only BigQuery query through the bq CLI (GH-1633).

    Only a single SELECT or WITH statement is accepted; DML, DDL,
    scripting, MERGE, EXPORT DATA, LOAD DATA, CALL, EXECUTE IMMEDIATE and
    EXTERNAL_QUERY are refused before bq runs, by a lexer that knows every
    GoogleSQL quote and comment form. ~/.bigqueryrc is not read, so it
    cannot add a destination table. The job times out server-side at 120 s.

    Args:
        sql: One Standard SQL SELECT/WITH statement. Address tables as
            `project.dataset.table`.
        project_id: Billing project. Defaults to the bq/gcloud default.
        location: Job location (e.g. US, EU), when the dataset needs one.
        max_rows: Rows to return, 1-10000.
        maximum_bytes_billed: Byte cap on the job, 1 B-1 TiB (default 10 GiB).
        dry_run: Validate and estimate bytes processed without running.

    Returns:
        Dictionary with keys: rows (list), row_count (int), max_rows (int),
        truncated (bool); or dry_run (true) and job (dict). A refused
        statement returns error with blocked=true.
    """
    from dev10x.db import bigquery

    return to_wire(
        await asyncio.to_thread(
            bigquery.query,
            sql=sql,
            project_id=project_id,
            location=location,
            max_rows=max_rows,
            maximum_bytes_billed=maximum_bytes_billed,
            dry_run=dry_run,
        )
    )


@server.tool()
async def bq_datasets(project_id: str, max_results: int = 200) -> dict:
    """List the BigQuery datasets in a project (GH-1633).

    Args:
        project_id: GCP project id.
        max_results: Datasets to return, 1-10000.

    Returns:
        Dictionary with keys: project_id, datasets (list).
    """
    from dev10x.db import bigquery

    return to_wire(
        await asyncio.to_thread(bigquery.datasets, project_id=project_id, max_results=max_results)
    )


@server.tool()
async def bq_tables(dataset: str, max_results: int = 200) -> dict:
    """List the tables in a BigQuery dataset (GH-1633).

    Args:
        dataset: Dataset as `project.dataset`.
        max_results: Tables to return, 1-10000.

    Returns:
        Dictionary with keys: dataset, tables (list).
    """
    from dev10x.db import bigquery

    return to_wire(
        await asyncio.to_thread(bigquery.tables, dataset=dataset, max_results=max_results)
    )


@server.tool()
async def bq_schema(table: str) -> dict:
    """Show a BigQuery table's column schema (GH-1633).

    Args:
        table: Table as `project.dataset.table`.

    Returns:
        Dictionary with keys: table, schema (list of fields).
    """
    from dev10x.db import bigquery

    return to_wire(await asyncio.to_thread(bigquery.schema, table=table))


def main() -> None:
    from dev10x.core.mcp.transport import select_transport

    server.run(transport=select_transport())
