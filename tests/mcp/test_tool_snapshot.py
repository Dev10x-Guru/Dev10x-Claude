"""Pin every registered MCP tool name and parameter schema (ADR-0034, GH-1529).

Stage A moves tool modules between namespaces; a move that renames a
tool or changes a parameter breaks every skill and permission rule that
spells it. A deliberate change regenerates the snapshot: delete
``tests/fixtures/mcp_tool_snapshot.json`` and re-run this file once.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP

from dev10x.mcp.server_cli import server as cli_server
from dev10x.mcp.server_db import server as db_server

SNAPSHOT_PATH = Path(__file__).parents[1] / "fixtures" / "mcp_tool_snapshot.json"


async def tool_schemas(*, server: FastMCP) -> dict[str, Any]:
    tools = await server.list_tools()
    return {tool.name: tool.inputSchema for tool in sorted(tools, key=lambda t: t.name)}


def render(*, snapshot: dict[str, Any]) -> str:
    return json.dumps(snapshot, indent=2, sort_keys=True) + "\n"


def recorded_snapshot(*, path: Path, actual: str) -> str:
    if not path.exists():
        path.write_text(actual)
        pytest.fail(f"Recorded a new MCP tool snapshot at {path}; re-run to verify.")
    return path.read_text()


@pytest.fixture(scope="module")
def actual_snapshot() -> str:
    async def collect() -> dict[str, Any]:
        return {
            "cli": await tool_schemas(server=cli_server),
            "db": await tool_schemas(server=db_server),
        }

    return render(snapshot=asyncio.run(collect()))


def test_registered_tools_match_the_snapshot(actual_snapshot: str) -> None:
    expected = recorded_snapshot(path=SNAPSHOT_PATH, actual=actual_snapshot)

    assert json.loads(actual_snapshot) == json.loads(expected), (
        "An MCP tool name or parameter schema changed. If that is deliberate, "
        f"delete {SNAPSHOT_PATH.name} and re-run this test to record it (GH-1529)."
    )


def test_snapshot_covers_both_servers(actual_snapshot: str) -> None:
    snapshot = json.loads(actual_snapshot)

    assert sorted(snapshot) == ["cli", "db"]
    assert snapshot["db"]


@pytest.mark.asyncio
async def test_tool_schemas_are_keyed_by_sorted_name() -> None:
    server = FastMCP(name="snapshot-probe")

    @server.tool()
    async def zeta(count: int) -> dict[str, Any]:
        return {"count": count}

    @server.tool()
    async def alpha(label: str = "x") -> dict[str, Any]:
        return {"label": label}

    schemas = await tool_schemas(server=server)

    assert list(schemas) == ["alpha", "zeta"]
    assert schemas["zeta"]["required"] == ["count"]


def test_recorded_snapshot_writes_a_missing_file_and_fails(tmp_path: Path) -> None:
    path = tmp_path / "snap.json"

    with pytest.raises(pytest.fail.Exception):
        recorded_snapshot(path=path, actual="{}\n")

    assert path.read_text() == "{}\n"


def test_recorded_snapshot_reads_an_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "snap.json"
    path.write_text('{"a": 1}\n')

    assert recorded_snapshot(path=path, actual="{}\n") == '{"a": 1}\n'
