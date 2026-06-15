"""Tests for server-initiated sampling (GH-343).

Covers:
- _sampling_enabled reads the env var correctly
- SamplingManager.enabled reflects the constructor flag
- SamplingManager.has_session tracks set_session attach/detach
- SamplingManager.create_message returns err when disabled
- SamplingManager.create_message returns err when no session attached
- SamplingManager.create_message returns ok with text/model/role on success
- SamplingManager.create_message reports non-text content with text=None
- SamplingManager.create_message returns err when the client raises
- request_sampling domain fn returns err when no manager registered
- request_sampling domain fn delegates to the manager
- wire_sampling_to_server registers InitializedNotification handler
- wire_sampling_to_server chains an existing InitializedNotification handler
- wire_sampling_to_server's handler captures the session
- wire_sampling_to_server's handler suppresses session-access errors
- get_manager returns the registered manager
- request_sampling MCP tool returns error when no manager
- request_sampling MCP tool returns the populated result on success
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sampling_mod = pytest.importorskip(
    "dev10x.mcp.sampling_manager",
    reason="mcp not installed",
)

SamplingManager = sampling_mod.SamplingManager
get_manager = sampling_mod.get_manager
request_sampling = sampling_mod.request_sampling
wire_sampling_to_server = sampling_mod.wire_sampling_to_server
_sampling_enabled = sampling_mod._sampling_enabled


# ── helpers ────────────────────────────────────────────────────────


def _make_create_message_result(
    *,
    text: str | None,
    content_type: str = "text",
    model: str = "claude-test",
    role: str = "assistant",
    stop_reason: str | None = "endTurn",
) -> Any:
    """Build a mock CreateMessageResult with the given content."""
    content = MagicMock()
    content.type = content_type
    content.text = text
    result = MagicMock()
    result.content = content
    result.model = model
    result.role = role
    result.stopReason = stop_reason
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


# ── _sampling_enabled ──────────────────────────────────────────────


class TestSamplingEnabled:
    def test_enabled_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEV10X_SAMPLING_ENABLED", raising=False)
        assert _sampling_enabled() is True

    def test_disabled_by_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_SAMPLING_ENABLED", "0")
        assert _sampling_enabled() is False

    def test_disabled_by_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_SAMPLING_ENABLED", "false")
        assert _sampling_enabled() is False

    def test_disabled_by_no(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_SAMPLING_ENABLED", "no")
        assert _sampling_enabled() is False

    def test_enabled_by_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_SAMPLING_ENABLED", "1")
        assert _sampling_enabled() is True


# ── SamplingManager ────────────────────────────────────────────────


class TestSamplingManager:
    def test_enabled_property_reflects_constructor_flag(self) -> None:
        assert SamplingManager(enabled=True).enabled is True
        assert SamplingManager(enabled=False).enabled is False

    def test_has_session_starts_false(self) -> None:
        assert SamplingManager().has_session is False

    def test_set_session_attaches_and_detaches(self) -> None:
        mgr = SamplingManager()
        session = AsyncMock()
        mgr.set_session(session=session)
        assert mgr.has_session is True
        mgr.set_session(session=None)
        assert mgr.has_session is False

    @pytest.mark.asyncio
    async def test_create_message_err_when_disabled(self) -> None:
        mgr = SamplingManager(enabled=False)
        mgr.set_session(session=AsyncMock())
        result = await mgr.create_message(prompt="hi")
        assert "error" in result.to_dict()

    @pytest.mark.asyncio
    async def test_create_message_err_without_session(self) -> None:
        mgr = SamplingManager(enabled=True)
        result = await mgr.create_message(prompt="hi")
        assert "error" in result.to_dict()

    @pytest.mark.asyncio
    async def test_create_message_success(self) -> None:
        mgr = SamplingManager(enabled=True)
        session = AsyncMock()
        session.create_message = AsyncMock(return_value=_make_create_message_result(text="42"))
        mgr.set_session(session=session)

        result = await mgr.create_message(
            prompt="What is 6 times 7?",
            system_prompt="Answer with a number.",
            max_tokens=16,
            temperature=0.0,
        )

        payload = result.to_dict()
        assert payload["text"] == "42"
        assert payload["content_type"] == "text"
        assert payload["model"] == "claude-test"
        assert payload["role"] == "assistant"
        assert payload["stop_reason"] == "endTurn"
        session.create_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_message_non_text_content(self) -> None:
        mgr = SamplingManager(enabled=True)
        session = AsyncMock()
        session.create_message = AsyncMock(
            return_value=_make_create_message_result(text=None, content_type="image")
        )
        mgr.set_session(session=session)

        payload = (await mgr.create_message(prompt="draw")).to_dict()
        assert payload["text"] is None
        assert payload["content_type"] == "image"

    @pytest.mark.asyncio
    async def test_create_message_err_when_client_raises(self) -> None:
        mgr = SamplingManager(enabled=True)
        session = AsyncMock()
        session.create_message = AsyncMock(side_effect=RuntimeError("not supported"))
        mgr.set_session(session=session)

        result = await mgr.create_message(prompt="hi")
        assert "error" in result.to_dict()


# ── request_sampling domain function ───────────────────────────────


class TestRequestSamplingDomain:
    @pytest.mark.asyncio
    async def test_err_when_no_manager(self) -> None:
        with patch("dev10x.mcp.sampling_manager.get_manager", return_value=None):
            result = await request_sampling(prompt="hi")
        assert "error" in result.to_dict()

    @pytest.mark.asyncio
    async def test_delegates_to_manager(self) -> None:
        mgr = SamplingManager(enabled=True)
        session = AsyncMock()
        session.create_message = AsyncMock(return_value=_make_create_message_result(text="ok"))
        mgr.set_session(session=session)

        with patch("dev10x.mcp.sampling_manager.get_manager", return_value=mgr):
            result = await request_sampling(prompt="hi", max_tokens=8)

        assert result.to_dict()["text"] == "ok"


# ── wire_sampling_to_server ────────────────────────────────────────


class TestWireSamplingToServer:
    def test_registers_initialized_handler_when_none_exists(self) -> None:
        import mcp.types as mcp_types

        stub = _make_server_stub()
        mgr = SamplingManager()
        wire_sampling_to_server(server=stub, manager=mgr)
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

        mgr = SamplingManager(enabled=True)
        wire_sampling_to_server(server=stub, manager=mgr)

        handler = stub.notification_handlers[mcp_types.InitializedNotification]
        await handler(MagicMock(spec=mcp_types.InitializedNotification))

        assert "existing" in call_log
        assert mgr.has_session is True

    @pytest.mark.asyncio
    async def test_initialized_handler_captures_session(self) -> None:
        import mcp.types as mcp_types

        stub = _make_server_stub()
        stub.request_context = MagicMock()
        stub.request_context.session = AsyncMock()

        mgr = SamplingManager(enabled=True)
        wire_sampling_to_server(server=stub, manager=mgr)

        handler = stub.notification_handlers[mcp_types.InitializedNotification]
        await handler(MagicMock(spec=mcp_types.InitializedNotification))

        assert mgr.has_session is True

    @pytest.mark.asyncio
    async def test_initialized_handler_suppresses_session_access_error(self) -> None:
        import mcp.types as mcp_types

        stub = _make_server_stub()
        stub.request_context = MagicMock()
        type(stub.request_context).session = property(
            lambda self: (_ for _ in ()).throw(RuntimeError("no session"))
        )

        mgr = SamplingManager(enabled=True)
        wire_sampling_to_server(server=stub, manager=mgr)

        handler = stub.notification_handlers[mcp_types.InitializedNotification]
        await handler(MagicMock(spec=mcp_types.InitializedNotification))  # Must not raise.

        assert mgr.has_session is False

    def test_get_manager_returns_registered_manager(self) -> None:
        stub = _make_server_stub()
        mgr = SamplingManager()
        wire_sampling_to_server(server=stub, manager=mgr)
        assert get_manager() is mgr


# ── request_sampling MCP tool ──────────────────────────────────────


class TestRequestSamplingTool:
    @pytest.mark.asyncio
    async def test_returns_error_when_no_manager(self) -> None:
        cli_server = pytest.importorskip("dev10x.mcp.server_cli", reason="mcp not installed")
        with patch("dev10x.mcp.sampling_manager.get_manager", return_value=None):
            result = await cli_server.request_sampling(prompt="hi")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_returns_populated_result_on_success(self) -> None:
        cli_server = pytest.importorskip("dev10x.mcp.server_cli", reason="mcp not installed")
        mgr = SamplingManager(enabled=True)
        session = AsyncMock()
        session.create_message = AsyncMock(return_value=_make_create_message_result(text="hello"))
        mgr.set_session(session=session)

        with patch("dev10x.mcp.sampling_manager.get_manager", return_value=mgr):
            result = await cli_server.request_sampling(prompt="hi", max_tokens=8)

        assert result["text"] == "hello"
        assert result["model"] == "claude-test"
