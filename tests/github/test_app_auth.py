from __future__ import annotations

import logging
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from dev10x.commands.github_app_api import GitHubAPIError
from dev10x.github import app_auth as auth


@pytest.fixture(autouse=True)
def clear_token_cache():
    auth._TOKEN_CACHE.clear()
    yield
    auth._TOKEN_CACHE.clear()


class TestAppConfigLoad:
    def test_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        result = auth.AppConfig.load(path=tmp_path / "missing.yaml")
        assert result is None

    def test_loads_full_config(self, tmp_path: Path) -> None:
        path = tmp_path / "github-app.yaml"
        path.write_text(
            "github_app:\n"
            "  app_id: '12345'\n"
            "  installation_id: '67890'\n"
            "  private_key_path: /keys/bot.pem\n"
            "  enabled: true\n"
        )
        result = auth.AppConfig.load(path=path)
        assert result is not None
        assert result.app_id == "12345"
        assert result.installation_id == "67890"
        assert result.private_key_path == Path("/keys/bot.pem")

    def test_returns_none_when_disabled(self, tmp_path: Path) -> None:
        path = tmp_path / "github-app.yaml"
        path.write_text(
            "github_app:\n  app_id: '1'\n  private_key_path: /k.pem\n  enabled: false\n"
        )
        assert auth.AppConfig.load(path=path) is None

    def test_returns_none_when_missing_required_keys(self, tmp_path: Path) -> None:
        path = tmp_path / "github-app.yaml"
        path.write_text("github_app:\n  enabled: true\n")
        assert auth.AppConfig.load(path=path) is None

    def test_returns_none_on_malformed_yaml(self, tmp_path: Path) -> None:
        path = tmp_path / "github-app.yaml"
        path.write_text("not: valid: yaml: [unclosed")
        assert auth.AppConfig.load(path=path) is None

    def test_expands_user_home_in_key_path(self, tmp_path: Path) -> None:
        path = tmp_path / "github-app.yaml"
        path.write_text("github_app:\n  app_id: '1'\n  private_key_path: ~/keys/bot.pem\n")
        result = auth.AppConfig.load(path=path)
        assert result is not None
        assert "~" not in str(result.private_key_path)


class TestGetBotToken:
    @pytest.fixture
    def app_config(self, tmp_path: Path) -> auth.AppConfig:
        key_path = tmp_path / "bot.pem"
        key_path.write_text(
            "-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----\n"
        )
        return auth.AppConfig(
            app_id="12345",
            private_key_path=key_path,
            installation_id="67890",
        )

    @pytest.mark.asyncio
    async def test_returns_none_when_config_missing(self) -> None:
        with patch.object(auth.AppConfig, "load", return_value=None):
            result = await auth.get_bot_token(repo="owner/repo")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_private_key_unreadable(
        self,
        tmp_path: Path,
    ) -> None:
        config = auth.AppConfig(
            app_id="1",
            private_key_path=tmp_path / "missing.pem",
            installation_id="2",
        )
        result = await auth.get_bot_token(repo="owner/repo", config=config)
        assert result is None

    @pytest.mark.asyncio
    async def test_mints_and_caches_token(
        self,
        app_config: auth.AppConfig,
    ) -> None:
        with (
            patch.object(auth, "_create_app_jwt", return_value="jwt-token"),
            patch.object(
                auth,
                "create_installation_token_full",
                return_value={"token": "ghs_secret", "expires_at": "2099-01-01T00:00:00Z"},
            ) as mock_exchange,
        ):
            first = await auth.get_bot_token(repo="owner/repo", config=app_config)
            second = await auth.get_bot_token(repo="owner/repo", config=app_config)

        assert first == "ghs_secret"
        assert second == "ghs_secret"
        assert mock_exchange.call_count == 1

    @pytest.mark.asyncio
    async def test_resolves_installation_id_when_absent(
        self,
        tmp_path: Path,
    ) -> None:
        key_path = tmp_path / "bot.pem"
        key_path.write_text("KEY")
        config = auth.AppConfig(app_id="1", private_key_path=key_path)

        with (
            patch.object(auth, "_create_app_jwt", return_value="jwt"),
            patch.object(auth, "get_repo_installation", return_value={"id": 99}) as mock_resolve,
            patch.object(
                auth,
                "create_installation_token_full",
                return_value={"token": "ghs_x", "expires_at": "2099-01-01T00:00:00Z"},
            ) as mock_exchange,
        ):
            token = await auth.get_bot_token(repo="owner/repo", config=config)

        assert token == "ghs_x"
        mock_resolve.assert_called_once_with(jwt_token="jwt", repo="owner/repo")
        mock_exchange.assert_called_once_with(jwt_token="jwt", installation_id=99)

    @pytest.mark.asyncio
    async def test_returns_none_when_token_exchange_fails(
        self,
        app_config: auth.AppConfig,
    ) -> None:
        with (
            patch.object(auth, "_create_app_jwt", return_value="jwt"),
            patch.object(
                auth,
                "create_installation_token_full",
                side_effect=GitHubAPIError("POST .../access_tokens -> 401 Unauthorized"),
            ),
        ):
            result = await auth.get_bot_token(repo="owner/repo", config=app_config)
        assert result is None

    @pytest.mark.asyncio
    async def test_refreshes_expired_cached_token(
        self,
        app_config: auth.AppConfig,
    ) -> None:
        auth._TOKEN_CACHE["owner/repo"] = auth._CachedToken(
            token="old", expires_at=time.time() - 10
        )
        with (
            patch.object(auth, "_create_app_jwt", return_value="jwt"),
            patch.object(
                auth,
                "create_installation_token_full",
                return_value={"token": "fresh", "expires_at": "2099-01-01T00:00:00Z"},
            ),
        ):
            token = await auth.get_bot_token(repo="owner/repo", config=app_config)
        assert token == "fresh"

    def test_module_has_no_subprocess_dependency(self) -> None:
        """GH-499: the App JWT must never be handed to a subprocess.

        Both App-auth calls now go through the in-process HTTP client
        (``dev10x.commands.github_app_api``) via ``asyncio.to_thread`` —
        there is no ``gh`` child process left in this module, so the JWT
        can never appear in argv / `ps` / `/proc/<pid>/cmdline`.
        """
        import inspect

        source = inspect.getsource(auth)
        assert "async_run" not in source
        assert "import subprocess" not in source
        assert '"gh"' not in source
        assert "'gh'" not in source

    @pytest.mark.asyncio
    async def test_resolve_and_exchange_use_bearer_jwt_via_http_client(
        self,
        tmp_path: Path,
    ) -> None:
        key_path = tmp_path / "bot.pem"
        key_path.write_text("KEY")
        config = auth.AppConfig(app_id="1", private_key_path=key_path)

        with (
            patch.object(auth, "_create_app_jwt", return_value="jwt"),
            patch.object(auth, "get_repo_installation", return_value={"id": 99}) as mock_resolve,
            patch.object(
                auth,
                "create_installation_token_full",
                return_value={"token": "ghs_x", "expires_at": "2099-01-01T00:00:00Z"},
            ) as mock_exchange,
        ):
            token = await auth.get_bot_token(repo="owner/repo", config=config)

        assert token == "ghs_x"
        mock_resolve.assert_called_once_with(jwt_token="jwt", repo="owner/repo")
        mock_exchange.assert_called_once_with(jwt_token="jwt", installation_id=99)

    @pytest.mark.asyncio
    async def test_falls_back_when_response_missing_token(
        self,
        app_config: auth.AppConfig,
    ) -> None:
        with (
            patch.object(auth, "_create_app_jwt", return_value="jwt"),
            patch.object(
                auth,
                "create_installation_token_full",
                return_value={"expires_at": "x"},
            ),
        ):
            result = await auth.get_bot_token(repo="owner/repo", config=app_config)
        assert result is None

    @pytest.mark.asyncio
    async def test_logs_warning_when_jwt_creation_fails(
        self,
        app_config: auth.AppConfig,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with (
            patch.object(auth, "_create_app_jwt", side_effect=ValueError("bad key")),
            caplog.at_level(logging.WARNING),
        ):
            result = await auth.get_bot_token(repo="owner/repo", config=app_config)
        assert result is None
        assert "JWT creation failed" in caplog.text

    @pytest.mark.asyncio
    async def test_logs_warning_when_installation_id_unresolvable(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        key_path = tmp_path / "bot.pem"
        key_path.write_text("KEY")
        config = auth.AppConfig(app_id="1", private_key_path=key_path)
        with (
            patch.object(auth, "_create_app_jwt", return_value="jwt"),
            patch.object(
                auth,
                "get_repo_installation",
                side_effect=GitHubAPIError("GET .../installation -> 404 Not Found"),
            ),
            caplog.at_level(logging.WARNING),
        ):
            result = await auth.get_bot_token(repo="owner/repo", config=config)
        assert result is None
        assert "installation lookup failed" in caplog.text

    @pytest.mark.asyncio
    async def test_installation_lookup_failure_does_not_leak_jwt(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A GitHubAPIError's message (server-side detail) never contains the JWT."""
        key_path = tmp_path / "bot.pem"
        key_path.write_text("KEY")
        config = auth.AppConfig(app_id="1", private_key_path=key_path)
        secret_jwt = "super-secret-jwt-value"
        with (
            patch.object(auth, "_create_app_jwt", return_value=secret_jwt),
            patch.object(
                auth,
                "get_repo_installation",
                side_effect=GitHubAPIError("GET .../installation -> 401 Unauthorized: {}"),
            ),
            caplog.at_level(logging.WARNING),
        ):
            result = await auth.get_bot_token(repo="owner/repo", config=config)
        assert result is None
        assert secret_jwt not in caplog.text

    @pytest.mark.asyncio
    async def test_token_exchange_failure_does_not_leak_jwt_or_token(
        self,
        app_config: auth.AppConfig,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        secret_jwt = "super-secret-jwt-value"
        with (
            patch.object(auth, "_create_app_jwt", return_value=secret_jwt),
            patch.object(
                auth,
                "create_installation_token_full",
                side_effect=GitHubAPIError("POST .../access_tokens -> 401 Unauthorized: {}"),
            ),
            caplog.at_level(logging.WARNING),
        ):
            result = await auth.get_bot_token(repo="owner/repo", config=app_config)
        assert result is None
        assert secret_jwt not in caplog.text
        assert "token exchange failed" in caplog.text.lower()
