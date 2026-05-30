"""Tests for transport selection logic (GH-335).

Covers:
- Default returns "stdio" when env var is absent
- Explicit values for all three transports
- Case-insensitive matching
- Invalid value raises ValueError with an informative message
- Both server main() functions delegate to select_transport()
"""

from __future__ import annotations

import pytest

from dev10x.mcp.transport import select_transport


class TestSelectTransport:
    def test_defaults_to_stdio_when_env_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEV10X_MCP_TRANSPORT", raising=False)
        assert select_transport() == "stdio"

    def test_defaults_to_stdio_when_env_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_MCP_TRANSPORT", "")
        assert select_transport() == "stdio"

    def test_returns_streamable_http(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_MCP_TRANSPORT", "streamable-http")
        assert select_transport() == "streamable-http"

    def test_returns_sse(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_MCP_TRANSPORT", "sse")
        assert select_transport() == "sse"

    def test_returns_stdio_explicit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_MCP_TRANSPORT", "stdio")
        assert select_transport() == "stdio"

    def test_case_insensitive_uppercase(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_MCP_TRANSPORT", "STREAMABLE-HTTP")
        assert select_transport() == "streamable-http"

    def test_case_insensitive_mixed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_MCP_TRANSPORT", "Sse")
        assert select_transport() == "sse"

    def test_strips_surrounding_whitespace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_MCP_TRANSPORT", "  stdio  ")
        assert select_transport() == "stdio"

    def test_invalid_value_raises_valueerror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_MCP_TRANSPORT", "websocket")
        with pytest.raises(ValueError, match="DEV10X_MCP_TRANSPORT"):
            select_transport()

    def test_error_message_lists_valid_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_MCP_TRANSPORT", "grpc")
        with pytest.raises(ValueError) as exc_info:
            select_transport()
        message = str(exc_info.value)
        assert "sse" in message
        assert "stdio" in message
        assert "streamable-http" in message


class TestServerMainDelegation:
    """Verify both server main() functions pass transport to server.run()."""

    def test_cli_server_main_uses_select_transport(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from unittest.mock import patch

        monkeypatch.setenv("DEV10X_MCP_TRANSPORT", "stdio")

        import dev10x.mcp.server_cli as cli_mod

        with patch.object(cli_mod.server, "run") as mock_run:
            cli_mod.main()
            mock_run.assert_called_once_with(transport="stdio")

    def test_cli_server_main_passes_streamable_http(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from unittest.mock import patch

        monkeypatch.setenv("DEV10X_MCP_TRANSPORT", "streamable-http")

        import dev10x.mcp.server_cli as cli_mod

        with patch.object(cli_mod.server, "run") as mock_run:
            cli_mod.main()
            mock_run.assert_called_once_with(transport="streamable-http")

    def test_db_server_main_uses_select_transport(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from unittest.mock import patch

        monkeypatch.setenv("DEV10X_MCP_TRANSPORT", "stdio")

        import dev10x.mcp.server_db as db_mod

        with patch.object(db_mod.server, "run") as mock_run:
            db_mod.main()
            mock_run.assert_called_once_with(transport="stdio")

    def test_db_server_main_passes_sse(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from unittest.mock import patch

        monkeypatch.setenv("DEV10X_MCP_TRANSPORT", "sse")

        import dev10x.mcp.server_db as db_mod

        with patch.object(db_mod.server, "run") as mock_run:
            db_mod.main()
            mock_run.assert_called_once_with(transport="sse")
