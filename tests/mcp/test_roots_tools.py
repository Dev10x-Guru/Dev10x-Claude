"""Tests for roots_tools MCP adapter (GH-580).

Covers ok → dict translation and the three manager states for
list_client_roots in src/dev10x/mcp/roots_tools.py.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from dev10x.mcp import server_cli as cli_server
from dev10x.mcp.roots_manager import ClientRoot, ClientRootsManager


class TestListClientRoots:
    @pytest.mark.asyncio
    async def test_returns_none_roots_and_disabled_when_no_manager(self) -> None:
        with patch("dev10x.mcp.roots_manager.get_manager", return_value=None):
            result = await cli_server.list_client_roots()

        assert result == {"roots": None, "enabled": False}

    @pytest.mark.asyncio
    async def test_returns_none_roots_before_session_established(self) -> None:
        mgr = ClientRootsManager(enabled=True)
        with patch("dev10x.mcp.roots_manager.get_manager", return_value=mgr):
            result = await cli_server.list_client_roots()

        assert result["roots"] is None
        assert result["enabled"] is True

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_client_declares_no_roots(self) -> None:
        mgr = ClientRootsManager(enabled=True)
        mgr._roots = []
        with patch("dev10x.mcp.roots_manager.get_manager", return_value=mgr):
            result = await cli_server.list_client_roots()

        assert result["roots"] == []
        assert result["enabled"] is True

    @pytest.mark.asyncio
    async def test_returns_populated_roots_after_refresh(self, tmp_path) -> None:
        mgr = ClientRootsManager(enabled=True)
        mgr._roots = [
            ClientRoot(uri=f"file://{tmp_path}/work", name="Work"),
            ClientRoot(uri=f"file://{tmp_path}/home", name=None),
        ]
        with patch("dev10x.mcp.roots_manager.get_manager", return_value=mgr):
            result = await cli_server.list_client_roots()

        assert len(result["roots"]) == 2
        assert result["roots"][0] == {"uri": f"file://{tmp_path}/work", "name": "Work"}
        assert result["roots"][1] == {"uri": f"file://{tmp_path}/home", "name": None}

    @pytest.mark.asyncio
    async def test_enabled_false_when_manager_disabled(self) -> None:
        mgr = ClientRootsManager(enabled=False)
        mgr._roots = []
        with patch("dev10x.mcp.roots_manager.get_manager", return_value=mgr):
            result = await cli_server.list_client_roots()

        assert result["enabled"] is False
