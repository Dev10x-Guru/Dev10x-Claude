"""Tests for daemon wiring with STDIO fallback (GH-338).

Covers:
- daemon_base_url(): host/port defaults and env var overrides
- daemon_mcp_url(): path suffix defaults and env var overrides
- select_transport_with_daemon_fallback():
    * explicit DEV10X_MCP_TRANSPORT != "auto" delegates to select_transport
    * "auto" mode with healthy daemon → "streamable-http"
    * "auto" mode with unhealthy daemon → "stdio"
    * absent env var (default "auto") with healthy daemon → "streamable-http"
    * absent env var (default "auto") with unhealthy daemon → "stdio"
    * invalid explicit transport raises ValueError (via select_transport)
- server_cli.main() uses select_transport_with_daemon_fallback
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from dev10x.mcp.wiring import (
    daemon_base_url,
    daemon_mcp_url,
    select_transport_with_daemon_fallback,
)

# ---------------------------------------------------------------------------
# daemon_base_url
# ---------------------------------------------------------------------------


class TestDaemonBaseUrl:
    def test_defaults_to_localhost_8000(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FASTMCP_HOST", raising=False)
        monkeypatch.delenv("FASTMCP_PORT", raising=False)
        assert daemon_base_url() == "http://127.0.0.1:8000"

    def test_reads_custom_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FASTMCP_HOST", "0.0.0.0")
        monkeypatch.delenv("FASTMCP_PORT", raising=False)
        assert daemon_base_url() == "http://0.0.0.0:8000"

    def test_reads_custom_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FASTMCP_HOST", raising=False)
        monkeypatch.setenv("FASTMCP_PORT", "9000")
        assert daemon_base_url() == "http://127.0.0.1:9000"

    def test_reads_custom_host_and_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FASTMCP_HOST", "192.168.1.10")
        monkeypatch.setenv("FASTMCP_PORT", "7777")
        assert daemon_base_url() == "http://192.168.1.10:7777"

    def test_strips_whitespace_from_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FASTMCP_HOST", "  localhost  ")
        monkeypatch.delenv("FASTMCP_PORT", raising=False)
        assert daemon_base_url() == "http://localhost:8000"

    def test_empty_host_env_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FASTMCP_HOST", "")
        monkeypatch.delenv("FASTMCP_PORT", raising=False)
        assert daemon_base_url() == "http://127.0.0.1:8000"

    def test_invalid_port_falls_back_to_default(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("FASTMCP_HOST", raising=False)
        monkeypatch.setenv("FASTMCP_PORT", "not-a-number")
        assert daemon_base_url() == "http://127.0.0.1:8000"

    def test_empty_port_env_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FASTMCP_HOST", raising=False)
        monkeypatch.setenv("FASTMCP_PORT", "")
        assert daemon_base_url() == "http://127.0.0.1:8000"


# ---------------------------------------------------------------------------
# daemon_mcp_url
# ---------------------------------------------------------------------------


class TestDaemonMcpUrl:
    def test_default_path_is_slash_mcp(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FASTMCP_HOST", raising=False)
        monkeypatch.delenv("FASTMCP_PORT", raising=False)
        monkeypatch.delenv("DEV10X_MCP_DAEMON_PATH", raising=False)
        assert daemon_mcp_url() == "http://127.0.0.1:8000/mcp"

    def test_custom_path_with_leading_slash(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("FASTMCP_HOST", raising=False)
        monkeypatch.delenv("FASTMCP_PORT", raising=False)
        monkeypatch.setenv("DEV10X_MCP_DAEMON_PATH", "/api/mcp")
        assert daemon_mcp_url() == "http://127.0.0.1:8000/api/mcp"

    def test_custom_path_without_leading_slash_gets_one_added(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("FASTMCP_HOST", raising=False)
        monkeypatch.delenv("FASTMCP_PORT", raising=False)
        monkeypatch.setenv("DEV10X_MCP_DAEMON_PATH", "mcp")
        assert daemon_mcp_url() == "http://127.0.0.1:8000/mcp"

    def test_empty_path_env_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FASTMCP_HOST", raising=False)
        monkeypatch.delenv("FASTMCP_PORT", raising=False)
        monkeypatch.setenv("DEV10X_MCP_DAEMON_PATH", "")
        assert daemon_mcp_url() == "http://127.0.0.1:8000/mcp"

    def test_combines_custom_host_port_and_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("FASTMCP_HOST", "10.0.0.1")
        monkeypatch.setenv("FASTMCP_PORT", "9999")
        monkeypatch.setenv("DEV10X_MCP_DAEMON_PATH", "/v2/mcp")
        assert daemon_mcp_url() == "http://10.0.0.1:9999/v2/mcp"


# ---------------------------------------------------------------------------
# select_transport_with_daemon_fallback
# ---------------------------------------------------------------------------


class TestSelectTransportWithDaemonFallback:
    # --- Explicit override paths (non-"auto" DEV10X_MCP_TRANSPORT) ---

    def test_explicit_stdio_delegates_without_health_check(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DEV10X_MCP_TRANSPORT", "stdio")
        with patch("dev10x.mcp.daemon.is_daemon_healthy") as mock_health:
            result = select_transport_with_daemon_fallback()
        assert result == "stdio"
        mock_health.assert_not_called()

    def test_explicit_streamable_http_delegates_without_health_check(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DEV10X_MCP_TRANSPORT", "streamable-http")
        with patch("dev10x.mcp.daemon.is_daemon_healthy") as mock_health:
            result = select_transport_with_daemon_fallback()
        assert result == "streamable-http"
        mock_health.assert_not_called()

    def test_explicit_sse_delegates_without_health_check(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DEV10X_MCP_TRANSPORT", "sse")
        with patch("dev10x.mcp.daemon.is_daemon_healthy") as mock_health:
            result = select_transport_with_daemon_fallback()
        assert result == "sse"
        mock_health.assert_not_called()

    def test_explicit_invalid_value_raises_valueerror(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DEV10X_MCP_TRANSPORT", "websocket")
        with pytest.raises(ValueError, match="DEV10X_MCP_TRANSPORT"):
            select_transport_with_daemon_fallback()

    def test_explicit_value_is_case_insensitive(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DEV10X_MCP_TRANSPORT", "STDIO")
        result = select_transport_with_daemon_fallback()
        assert result == "stdio"

    # --- "auto" mode (DEV10X_MCP_TRANSPORT="auto") ---

    def test_auto_mode_with_healthy_daemon_returns_streamable_http(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DEV10X_MCP_TRANSPORT", "auto")
        with patch("dev10x.mcp.wiring.is_daemon_healthy", return_value=True):
            result = select_transport_with_daemon_fallback()
        assert result == "streamable-http"

    def test_auto_mode_with_unhealthy_daemon_returns_stdio(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DEV10X_MCP_TRANSPORT", "auto")
        with patch("dev10x.mcp.wiring.is_daemon_healthy", return_value=False):
            result = select_transport_with_daemon_fallback()
        assert result == "stdio"

    def test_auto_mode_is_case_insensitive(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DEV10X_MCP_TRANSPORT", "AUTO")
        with patch("dev10x.mcp.wiring.is_daemon_healthy", return_value=True):
            result = select_transport_with_daemon_fallback()
        assert result == "streamable-http"

    # --- Absent env var (default "auto" behaviour) ---

    def test_absent_env_var_with_healthy_daemon_returns_streamable_http(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("DEV10X_MCP_TRANSPORT", raising=False)
        with patch("dev10x.mcp.wiring.is_daemon_healthy", return_value=True):
            result = select_transport_with_daemon_fallback()
        assert result == "streamable-http"

    def test_absent_env_var_with_unhealthy_daemon_returns_stdio(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("DEV10X_MCP_TRANSPORT", raising=False)
        with patch("dev10x.mcp.wiring.is_daemon_healthy", return_value=False):
            result = select_transport_with_daemon_fallback()
        assert result == "stdio"

    def test_empty_env_var_with_healthy_daemon_returns_streamable_http(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DEV10X_MCP_TRANSPORT", "")
        with patch("dev10x.mcp.wiring.is_daemon_healthy", return_value=True):
            result = select_transport_with_daemon_fallback()
        assert result == "streamable-http"

    def test_daemon_health_check_is_called_exactly_once(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("DEV10X_MCP_TRANSPORT", raising=False)
        with patch("dev10x.mcp.wiring.is_daemon_healthy", return_value=False) as mock:
            select_transport_with_daemon_fallback()
        mock.assert_called_once_with()


# ---------------------------------------------------------------------------
# server_cli.main() integration
# ---------------------------------------------------------------------------


class TestServerCliMainUsesWiring:
    """Verify that server_cli.main() delegates to select_transport_with_daemon_fallback."""

    def test_main_calls_wiring_when_daemon_healthy(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("DEV10X_MCP_TRANSPORT", raising=False)
        import dev10x.mcp.server_cli as cli_mod

        with (
            patch("dev10x.mcp.wiring.is_daemon_healthy", return_value=True),
            patch.object(cli_mod.server, "run") as mock_run,
        ):
            cli_mod.main()
        mock_run.assert_called_once_with(transport="streamable-http")

    def test_main_falls_back_to_stdio_when_daemon_absent(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("DEV10X_MCP_TRANSPORT", raising=False)
        import dev10x.mcp.server_cli as cli_mod

        with (
            patch("dev10x.mcp.wiring.is_daemon_healthy", return_value=False),
            patch.object(cli_mod.server, "run") as mock_run,
        ):
            cli_mod.main()
        mock_run.assert_called_once_with(transport="stdio")

    def test_main_honours_explicit_stdio_override(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DEV10X_MCP_TRANSPORT", "stdio")
        import dev10x.mcp.server_cli as cli_mod

        with (
            patch("dev10x.mcp.daemon.is_daemon_healthy") as mock_health,
            patch.object(cli_mod.server, "run") as mock_run,
        ):
            cli_mod.main()
        mock_health.assert_not_called()
        mock_run.assert_called_once_with(transport="stdio")
