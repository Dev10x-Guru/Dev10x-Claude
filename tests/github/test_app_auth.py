from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from dev10x.github import app_auth as auth


@pytest.fixture(autouse=True)
def clear_token_cache():
    auth._clear_cache()
    yield
    auth._clear_cache()


def _completed(
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


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
        token_response = _completed(
            stdout=json.dumps({"token": "ghs_secret", "expires_at": "2099-01-01T00:00:00Z"})
        )
        with (
            patch.object(auth, "_create_app_jwt", return_value="jwt-token"),
            patch(
                "dev10x.github.app_auth.async_run",
                new_callable=AsyncMock,
                return_value=token_response,
            ) as mock_run,
        ):
            first = await auth.get_bot_token(repo="owner/repo", config=app_config)
            second = await auth.get_bot_token(repo="owner/repo", config=app_config)

        assert first == "ghs_secret"
        assert second == "ghs_secret"
        assert mock_run.call_count == 1

    @pytest.mark.asyncio
    async def test_resolves_installation_id_when_absent(
        self,
        tmp_path: Path,
    ) -> None:
        key_path = tmp_path / "bot.pem"
        key_path.write_text("KEY")
        config = auth.AppConfig(app_id="1", private_key_path=key_path)

        responses = [
            _completed(stdout=json.dumps({"id": 99})),
            _completed(
                stdout=json.dumps({"token": "ghs_x", "expires_at": "2099-01-01T00:00:00Z"})
            ),
        ]
        with (
            patch.object(auth, "_create_app_jwt", return_value="jwt"),
            patch(
                "dev10x.github.app_auth.async_run",
                new_callable=AsyncMock,
                side_effect=responses,
            ) as mock_run,
        ):
            token = await auth.get_bot_token(repo="owner/repo", config=config)

        assert token == "ghs_x"
        assert mock_run.call_count == 2
        assert "/repos/owner/repo/installation" in mock_run.call_args_list[0].kwargs["args"]
        assert "/app/installations/99/access_tokens" in mock_run.call_args_list[1].kwargs["args"]

    @pytest.mark.asyncio
    async def test_returns_none_when_token_exchange_fails(
        self,
        app_config: auth.AppConfig,
    ) -> None:
        with (
            patch.object(auth, "_create_app_jwt", return_value="jwt"),
            patch(
                "dev10x.github.app_auth.async_run",
                new_callable=AsyncMock,
                return_value=_completed(returncode=1, stderr="bad"),
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
        new_response = _completed(
            stdout=json.dumps({"token": "fresh", "expires_at": "2099-01-01T00:00:00Z"})
        )
        with (
            patch.object(auth, "_create_app_jwt", return_value="jwt"),
            patch(
                "dev10x.github.app_auth.async_run",
                new_callable=AsyncMock,
                return_value=new_response,
            ),
        ):
            token = await auth.get_bot_token(repo="owner/repo", config=app_config)
        assert token == "fresh"

    @pytest.mark.asyncio
    async def test_falls_back_when_response_missing_token(
        self,
        app_config: auth.AppConfig,
    ) -> None:
        with (
            patch.object(auth, "_create_app_jwt", return_value="jwt"),
            patch(
                "dev10x.github.app_auth.async_run",
                new_callable=AsyncMock,
                return_value=_completed(stdout=json.dumps({"expires_at": "x"})),
            ),
        ):
            result = await auth.get_bot_token(repo="owner/repo", config=app_config)
        assert result is None
