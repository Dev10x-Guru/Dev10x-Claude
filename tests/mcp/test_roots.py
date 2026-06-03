"""Tests for client-roots awareness (GH-344).

Covers:
- ClientRoot.contains correctly identifies paths inside/outside a root
- ClientRoot.path resolves file:// URIs and returns None for non-file URIs
- ClientRoot.to_dict returns the expected shape
- ClientRootsManager.roots starts as None
- ClientRootsManager.is_within_roots returns True when roots is None/empty
- ClientRootsManager.refresh fetches roots from session and caches them
- ClientRootsManager.refresh is a no-op when disabled
- ClientRootsManager.refresh is a no-op when no session is attached
- ClientRootsManager.refresh suppresses exceptions from list_roots
- ClientRootsManager.set_session(None) clears cached roots
- wire_roots_to_server registers InitializedNotification handler
- wire_roots_to_server chains with existing InitializedNotification handler
- wire_roots_to_server registers RootsListChangedNotification handler
- get_manager returns the registered manager
- _roots_enabled reads the env var correctly
- list_client_roots MCP tool returns None roots before session
- list_client_roots MCP tool returns populated roots after refresh
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

roots_mod = pytest.importorskip(
    "dev10x.mcp.roots_manager",
    reason="mcp not installed",
)

ClientRoot = roots_mod.ClientRoot
ClientRootsManager = roots_mod.ClientRootsManager
get_manager = roots_mod.get_manager
wire_roots_to_server = roots_mod.wire_roots_to_server
_roots_enabled = roots_mod._roots_enabled


# ── helpers ────────────────────────────────────────────────────────


def _make_list_roots_result(uris: list[str]) -> Any:
    """Build a mock ListRootsResult with the given URIs."""
    roots = []
    for uri in uris:
        r = MagicMock()
        r.uri = uri
        r.name = None
        roots.append(r)
    result = MagicMock()
    result.roots = roots
    return result


def _make_server_stub(existing_init_handler: Any = None) -> MagicMock:
    """Build a minimal low-level server stub."""
    stub = MagicMock()
    handlers: dict[type, Any] = {}
    if existing_init_handler is not None:
        import mcp.types as mcp_types

        handlers[mcp_types.InitializedNotification] = existing_init_handler
    stub.notification_handlers = handlers
    return stub


# ── ClientRoot ─────────────────────────────────────────────────────


class TestClientRoot:
    def test_path_resolves_file_uri(self, tmp_path: Path) -> None:
        root = ClientRoot(uri=f"file://{tmp_path}")
        assert root.path == tmp_path.resolve()

    def test_path_is_none_for_non_file_uri(self) -> None:
        root = ClientRoot(uri="https://example.com/root")
        assert root.path is None

    def test_contains_child_path(self, tmp_path: Path) -> None:
        root = ClientRoot(uri=f"file://{tmp_path}")
        child = tmp_path / "subdir" / "file.txt"
        assert root.contains(candidate=child) is True

    def test_contains_returns_false_for_sibling(self, tmp_path: Path) -> None:
        sibling = tmp_path.parent / "other"
        root = ClientRoot(uri=f"file://{tmp_path}")
        assert root.contains(candidate=sibling) is False

    def test_contains_returns_false_for_non_file_uri(self, tmp_path: Path) -> None:
        root = ClientRoot(uri="https://example.com/root")
        assert root.contains(candidate=tmp_path) is False

    def test_to_dict_returns_uri_and_name(self) -> None:
        root = ClientRoot(uri="file:///tmp/x", name="MyRoot")
        assert root.to_dict() == {"uri": "file:///tmp/x", "name": "MyRoot"}

    def test_to_dict_name_is_none_when_unset(self) -> None:
        root = ClientRoot(uri="file:///tmp/x")
        assert root.to_dict()["name"] is None

    def test_repr_includes_uri(self) -> None:
        root = ClientRoot(uri="file:///tmp/x")
        assert "file:///tmp/x" in repr(root)


# ── ClientRootsManager ─────────────────────────────────────────────


class TestClientRootsManager:
    def test_roots_starts_as_none(self) -> None:
        mgr = ClientRootsManager()
        assert mgr.roots is None

    def test_enabled_property_reflects_constructor_flag(self) -> None:
        assert ClientRootsManager(enabled=True).enabled is True
        assert ClientRootsManager(enabled=False).enabled is False

    def test_is_within_roots_true_when_no_roots(self, tmp_path: Path) -> None:
        mgr = ClientRootsManager()
        assert mgr.is_within_roots(cwd=tmp_path) is True

    def test_is_within_roots_true_when_empty_roots(self, tmp_path: Path) -> None:
        mgr = ClientRootsManager()
        mgr._roots = []
        assert mgr.is_within_roots(cwd=tmp_path) is True

    def test_is_within_roots_true_when_inside_declared_root(self, tmp_path: Path) -> None:
        mgr = ClientRootsManager()
        mgr._roots = [ClientRoot(uri=f"file://{tmp_path}")]
        child = tmp_path / "sub"
        assert mgr.is_within_roots(cwd=child) is True

    def test_is_within_roots_false_when_outside_declared_root(self, tmp_path: Path) -> None:
        mgr = ClientRootsManager()
        sub = tmp_path / "allowed"
        mgr._roots = [ClientRoot(uri=f"file://{sub}")]
        other = tmp_path / "forbidden"
        assert mgr.is_within_roots(cwd=other) is False

    def test_set_session_none_clears_roots(self) -> None:
        mgr = ClientRootsManager()
        mgr._roots = [ClientRoot(uri="file:///tmp/x")]
        mgr.set_session(session=None)
        assert mgr.roots is None

    @pytest.mark.asyncio
    async def test_refresh_fetches_roots_from_session(self, tmp_path: Path) -> None:
        mgr = ClientRootsManager(enabled=True)
        session = AsyncMock()
        session.list_roots = AsyncMock(
            return_value=_make_list_roots_result([f"file://{tmp_path}"])
        )
        mgr.set_session(session=session)

        await mgr.refresh()

        assert mgr.roots is not None
        assert len(mgr.roots) == 1
        assert mgr.roots[0].uri == f"file://{tmp_path}"

    @pytest.mark.asyncio
    async def test_refresh_noop_when_disabled(self) -> None:
        mgr = ClientRootsManager(enabled=False)
        session = AsyncMock()
        mgr.set_session(session=session)

        await mgr.refresh()

        session.list_roots.assert_not_awaited()
        assert mgr.roots is None

    @pytest.mark.asyncio
    async def test_refresh_noop_without_session(self) -> None:
        mgr = ClientRootsManager(enabled=True)
        # No session attached.
        await mgr.refresh()
        assert mgr.roots is None

    @pytest.mark.asyncio
    async def test_refresh_suppresses_list_roots_exception(self) -> None:
        mgr = ClientRootsManager(enabled=True)
        session = AsyncMock()
        session.list_roots = AsyncMock(side_effect=RuntimeError("not supported"))
        mgr.set_session(session=session)

        await mgr.refresh()  # Must not raise.

        assert mgr.roots is None


# ── wire_roots_to_server ───────────────────────────────────────────


class TestWireRootsToServer:
    def test_registers_roots_changed_handler(self) -> None:
        import mcp.types as mcp_types

        stub = _make_server_stub()
        mgr = ClientRootsManager()
        wire_roots_to_server(server=stub, manager=mgr)
        assert mcp_types.RootsListChangedNotification in stub.notification_handlers

    def test_registers_initialized_handler_when_none_exists(self) -> None:
        import mcp.types as mcp_types

        stub = _make_server_stub()
        mgr = ClientRootsManager()
        wire_roots_to_server(server=stub, manager=mgr)
        assert mcp_types.InitializedNotification in stub.notification_handlers

    @pytest.mark.asyncio
    async def test_chains_existing_initialized_handler(self) -> None:
        import mcp.types as mcp_types

        call_log: list[str] = []

        async def existing(n: mcp_types.InitializedNotification) -> None:
            call_log.append("existing")

        stub = _make_server_stub(existing_init_handler=existing)
        stub.request_context = MagicMock()
        stub.request_context.session = AsyncMock()
        stub.request_context.session.list_roots = AsyncMock(
            return_value=_make_list_roots_result([])
        )

        mgr = ClientRootsManager(enabled=True)
        wire_roots_to_server(server=stub, manager=mgr)

        handler = stub.notification_handlers[mcp_types.InitializedNotification]
        notification = MagicMock(spec=mcp_types.InitializedNotification)
        await handler(notification)

        assert "existing" in call_log

    @pytest.mark.asyncio
    async def test_initialized_handler_calls_refresh(self) -> None:
        import mcp.types as mcp_types

        stub = _make_server_stub()
        stub.request_context = MagicMock()
        stub.request_context.session = AsyncMock()
        stub.request_context.session.list_roots = AsyncMock(
            return_value=_make_list_roots_result(["file:///tmp/test"])
        )

        mgr = ClientRootsManager(enabled=True)
        wire_roots_to_server(server=stub, manager=mgr)

        handler = stub.notification_handlers[mcp_types.InitializedNotification]
        await handler(MagicMock(spec=mcp_types.InitializedNotification))

        assert mgr.roots is not None
        assert len(mgr.roots) == 1

    @pytest.mark.asyncio
    async def test_roots_changed_handler_schedules_refresh(self) -> None:
        import mcp.types as mcp_types

        stub = _make_server_stub()
        mgr = ClientRootsManager(enabled=False)
        wire_roots_to_server(server=stub, manager=mgr)

        handler = stub.notification_handlers[mcp_types.RootsListChangedNotification]
        with patch.object(asyncio, "create_task") as mock_create_task:
            await handler(MagicMock(spec=mcp_types.RootsListChangedNotification))
            mock_create_task.assert_called_once()

    def test_get_manager_returns_registered_manager(self) -> None:
        stub = _make_server_stub()
        mgr = ClientRootsManager()
        wire_roots_to_server(server=stub, manager=mgr)
        assert get_manager() is mgr

    @pytest.mark.asyncio
    async def test_initialized_handler_suppresses_session_access_error(self) -> None:
        import mcp.types as mcp_types

        stub = _make_server_stub()
        # Raise when the handler tries to access request_context.session.
        stub.request_context = MagicMock()
        type(stub.request_context).session = property(
            lambda self: (_ for _ in ()).throw(RuntimeError("no session"))
        )

        mgr = ClientRootsManager(enabled=True)
        wire_roots_to_server(server=stub, manager=mgr)

        handler = stub.notification_handlers[mcp_types.InitializedNotification]
        await handler(MagicMock(spec=mcp_types.InitializedNotification))  # Must not raise.

        assert mgr.roots is None


# ── _roots_enabled ─────────────────────────────────────────────────


class TestRootsEnabled:
    def test_enabled_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEV10X_ROOTS_ENABLED", raising=False)
        assert _roots_enabled() is True

    def test_disabled_by_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_ROOTS_ENABLED", "0")
        assert _roots_enabled() is False

    def test_disabled_by_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_ROOTS_ENABLED", "false")
        assert _roots_enabled() is False

    def test_enabled_by_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_ROOTS_ENABLED", "1")
        assert _roots_enabled() is True


# ── list_client_roots MCP tool ─────────────────────────────────────


class TestListClientRootsTool:
    @pytest.mark.asyncio
    async def test_returns_none_roots_when_no_manager(self) -> None:
        cli_server = pytest.importorskip("dev10x.mcp.server_cli", reason="mcp not installed")
        with patch("dev10x.mcp.roots_manager.get_manager", return_value=None):
            result = await cli_server.list_client_roots()
        assert result == {"roots": None, "enabled": False}

    @pytest.mark.asyncio
    async def test_returns_none_roots_before_refresh(self) -> None:
        cli_server = pytest.importorskip("dev10x.mcp.server_cli", reason="mcp not installed")
        mgr = ClientRootsManager(enabled=True)
        with patch("dev10x.mcp.roots_manager.get_manager", return_value=mgr):
            result = await cli_server.list_client_roots()
        assert result["roots"] is None
        assert result["enabled"] is True

    @pytest.mark.asyncio
    async def test_returns_populated_roots_after_refresh(self, tmp_path: Path) -> None:
        cli_server = pytest.importorskip("dev10x.mcp.server_cli", reason="mcp not installed")
        mgr = ClientRootsManager(enabled=True)
        mgr._roots = [ClientRoot(uri=f"file://{tmp_path}", name="Work")]
        with patch("dev10x.mcp.roots_manager.get_manager", return_value=mgr):
            result = await cli_server.list_client_roots()
        assert result["roots"] == [{"uri": f"file://{tmp_path}", "name": "Work"}]
        assert result["enabled"] is True

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_roots_declared(self) -> None:
        cli_server = pytest.importorskip("dev10x.mcp.server_cli", reason="mcp not installed")
        mgr = ClientRootsManager(enabled=True)
        mgr._roots = []
        with patch("dev10x.mcp.roots_manager.get_manager", return_value=mgr):
            result = await cli_server.list_client_roots()
        assert result["roots"] == []
