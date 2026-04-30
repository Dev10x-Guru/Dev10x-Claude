"""Database MCP tool implementations.

Provides read-only SQL query execution via db.sh wrapper script.
"""

from __future__ import annotations

import json
from typing import Any

from dev10x.domain.result import Result, err, ok
from dev10x.domain.sql import is_read_only_sql
from dev10x.subprocess_utils import run_script


def query(database: str, sql: str) -> Result[dict[str, Any]]:
    """Execute a read-only SQL query against a database."""
    if not is_read_only_sql(sql):
        return err(
            "Write operations are prohibited. "
            "Only read-only queries (SELECT, WITH, EXPLAIN, SHOW) are allowed.",
            blocked=True,
        )

    result = run_script("skills/db-psql/scripts/db.sh", database, sql)

    if result.returncode != 0:
        return err(result.stderr.strip())

    try:
        return ok(json.loads(result.stdout))
    except json.JSONDecodeError:
        return ok({"raw_output": result.stdout})
