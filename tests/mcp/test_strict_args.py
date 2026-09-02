"""Unknown tool parameters must fail loud, not vanish (GH-1122)."""

from __future__ import annotations

from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from dev10x.mcp.strict_args import (
    UnknownToolParameterError,
    enforce_strict_arguments,
)


@pytest.fixture()
def server_with_tool() -> FastMCP:
    server = FastMCP(name="test-server")

    @server.tool()
    async def edit_thing(number: int, body: str | None = None) -> dict[str, Any]:
        return {"number": number, "body": body}

    return server


class TestEnforceStrictArguments:
    @pytest.mark.asyncio
    async def test_unknown_parameter_is_rejected_by_name(self, server_with_tool: FastMCP) -> None:
        enforce_strict_arguments(server_with_tool)

        # FastMCP wraps a handler exception in ToolError, which is what
        # reaches the client as an error response — so that, not the raw
        # cause, is the contract a caller can rely on.
        with pytest.raises(ToolError) as excinfo:
            await server_with_tool._tool_manager.call_tool(
                "edit_thing", {"number": 1120, "milestone": 55}
            )

        assert "milestone" in str(excinfo.value)
        assert isinstance(excinfo.value.__cause__, UnknownToolParameterError)

    @pytest.mark.asyncio
    async def test_error_names_the_running_plugin_version(self, server_with_tool: FastMCP) -> None:
        # The whole point of naming the version: a caller whose docs list
        # the parameter must be able to tell version lag from a rejection
        # by GitHub.
        enforce_strict_arguments(server_with_tool)

        with pytest.raises(ToolError) as excinfo:
            await server_with_tool._tool_manager.call_tool(
                "edit_thing", {"number": 1, "nope": True}
            )

        assert "plugin version" in str(excinfo.value)
        assert "NOT applied" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_known_parameters_still_reach_the_handler(
        self, server_with_tool: FastMCP
    ) -> None:
        enforce_strict_arguments(server_with_tool)

        result = await server_with_tool._tool_manager.call_tool(
            "edit_thing", {"number": 7, "body": "hello"}, convert_result=False
        )

        assert result == {"number": 7, "body": "hello"}

    @pytest.mark.asyncio
    async def test_omitted_optional_parameter_still_defaults(
        self, server_with_tool: FastMCP
    ) -> None:
        enforce_strict_arguments(server_with_tool)

        result = await server_with_tool._tool_manager.call_tool(
            "edit_thing", {"number": 7}, convert_result=False
        )

        assert result == {"number": 7, "body": None}

    def test_pass_reports_the_tools_it_converted(self, server_with_tool: FastMCP) -> None:
        assert enforce_strict_arguments(server_with_tool) == ["edit_thing"]

    def test_second_pass_is_idempotent(self, server_with_tool: FastMCP) -> None:
        enforce_strict_arguments(server_with_tool)

        assert enforce_strict_arguments(server_with_tool) == []

    def test_field_alias_is_an_accepted_inbound_name(self) -> None:
        # A pydantic alias is the wire name the client actually sends, so
        # rejecting it would break a legitimate call rather than a typo'd one.
        from pydantic import BaseModel, Field

        from dev10x.mcp.strict_args import _accepted_names

        class Aliased(BaseModel):
            pr_number: int = Field(alias="prNumber")

        assert _accepted_names(Aliased) == {"pr_number", "prNumber"}

    def test_missing_tool_manager_raises_rather_than_silently_doing_nothing(
        self,
    ) -> None:
        # `_tool_manager` is private FastMCP API. A no-op on drift would
        # restore the exact silent-drop this module exists to remove.
        class Drifted:
            pass

        with pytest.raises(RuntimeError, match="strict-argument pass"):
            enforce_strict_arguments(Drifted())


class TestRealServerIsCovered:
    def test_cli_server_tools_are_strict_on_import(self) -> None:
        from dev10x.mcp.server_cli import server
        from dev10x.mcp.strict_args import StrictFuncMetadata

        tools = server._tool_manager.list_tools()

        assert tools, "expected the cli server to register tools"
        assert all(isinstance(t.fn_metadata, StrictFuncMetadata) for t in tools)
