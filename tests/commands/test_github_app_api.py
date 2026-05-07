"""Tests for the GitHub API helpers used by the setup wizard."""

from __future__ import annotations

import io
import json
import urllib.error
from typing import Any
from unittest.mock import patch

import pytest

from dev10x.commands import github_app_api as api


@pytest.fixture
def fake_pem() -> str:
    # A real RSA key generated for tests — verifying the JWT path requires
    # a parseable key, so we generate one inline.
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem.decode()


def _fake_response(payload: Any, status: int = 200) -> io.BytesIO:
    body = io.BytesIO(json.dumps(payload).encode())
    body.status = status  # type: ignore[attr-defined]
    body.__enter__ = lambda self: self  # type: ignore[assignment]
    body.__exit__ = lambda self, *args: None  # type: ignore[assignment]
    return body


class TestMintAppJwt:
    def test_returns_string(self, fake_pem: str) -> None:
        token = api.mint_app_jwt(app_id="12345", private_key=fake_pem)
        assert isinstance(token, str)
        # Three dot-separated segments
        assert token.count(".") == 2


class TestGetApp:
    def test_parses_response(self) -> None:
        with patch.object(api.urllib.request, "urlopen") as mocked:
            mocked.return_value = _fake_response({"id": 12345, "slug": "dev10x-bot"})
            result = api.get_app(jwt_token="JWT")

        assert result == {"id": 12345, "slug": "dev10x-bot"}
        called_request = mocked.call_args[0][0]
        assert called_request.full_url == f"{api.API_ROOT}/app"
        assert called_request.headers["Authorization"] == "Bearer JWT"

    def test_raises_on_http_error(self) -> None:
        http_error = urllib.error.HTTPError(
            url="https://api.github.com/app",
            code=401,
            msg="Unauthorized",
            hdrs={},  # type: ignore[arg-type]
            fp=io.BytesIO(b'{"message":"Bad credentials"}'),
        )
        with patch.object(api.urllib.request, "urlopen", side_effect=http_error):
            with pytest.raises(api.GitHubAPIError) as excinfo:
                api.get_app(jwt_token="JWT")

        assert "401" in str(excinfo.value)
        assert "Bad credentials" in str(excinfo.value)


class TestListInstallations:
    def test_returns_list(self) -> None:
        installations = [
            {"id": 1, "account": {"login": "Dev10x-Guru"}},
            {"id": 2, "account": {"login": "tiretutorinc"}},
        ]
        with patch.object(api.urllib.request, "urlopen") as mocked:
            mocked.return_value = _fake_response(installations)
            result = api.list_installations(jwt_token="JWT")

        assert result == installations


class TestCreateInstallationToken:
    def test_returns_token_field(self) -> None:
        with patch.object(api.urllib.request, "urlopen") as mocked:
            mocked.return_value = _fake_response({"token": "ghs_xyz", "expires_at": "..."})
            result = api.create_installation_token(jwt_token="JWT", installation_id=99)

        assert result == "ghs_xyz"
        called_request = mocked.call_args[0][0]
        assert called_request.method == "POST"
        assert called_request.full_url == f"{api.API_ROOT}/app/installations/99/access_tokens"


class TestListInstallationRepositories:
    def test_unwraps_repositories_key(self) -> None:
        payload = {
            "total_count": 1,
            "repositories": [{"name": "Dev10x-Claude", "owner": {"login": "Dev10x-Guru"}}],
        }
        with patch.object(api.urllib.request, "urlopen") as mocked:
            mocked.return_value = _fake_response(payload)
            result = api.list_installation_repositories(token="TOK")

        assert result == payload["repositories"]


class TestGetRepo:
    def test_returns_repo_payload(self) -> None:
        with patch.object(api.urllib.request, "urlopen") as mocked:
            mocked.return_value = _fake_response({"id": 1, "name": "Dev10x-Claude"})
            result = api.get_repo(token="TOK", owner="Dev10x-Guru", repo="Dev10x-Claude")

        assert result == {"id": 1, "name": "Dev10x-Claude"}
