"""Where core finds ``db.sh`` after it moved to ``dev10x-db`` (GH-1566).

The ``db`` MCP server and the DX004 SQL-safety hook stay in core
(ADR-0034, B3), while the db-psql skill that owns the script ships in
the satellite. Both resolve the script here so they cannot disagree.
"""

from __future__ import annotations

from pathlib import Path

from dev10x.core.paths import satellite_script

DB_KEY = "db"
DB_PLUGIN_NAME = "dev10x-db"
DB_SCRIPT_SKILL = "db-psql"
DB_SCRIPT = "db.sh"


def db_script(*, plugin_root: Path) -> str:
    return satellite_script(
        plugin_root=plugin_root,
        key=DB_KEY,
        plugin_name=DB_PLUGIN_NAME,
        skill=DB_SCRIPT_SKILL,
        rel=DB_SCRIPT,
    )


__all__ = ["DB_KEY", "DB_PLUGIN_NAME", "DB_SCRIPT", "DB_SCRIPT_SKILL", "db_script"]
