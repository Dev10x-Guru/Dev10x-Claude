"""Tests for the importable gchat_notify transport module."""

from __future__ import annotations

import json

import pytest

from dev10x.domain.common.result import ErrorResult, SuccessResult, err, ok
from dev10x.skills.notifications import gchat_notify as mod


@pytest.fixture(autouse=True)
def _reset_config_cache() -> None:
    mod._config = None


class TestResolveSpaceId:
    def test_resolves_known_alias(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            mod, "_load_config", lambda: {"spaces": {"tt-reviews": {"space_id": "AAAA123"}}}
        )
        result = mod.resolve_space_id("tt-reviews")
        assert isinstance(result, SuccessResult)
        assert result.value == "AAAA123"

    def test_errors_on_unknown_alias(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_load_config", lambda: {"spaces": {}})
        result = mod.resolve_space_id("missing")
        assert isinstance(result, ErrorResult)
        assert "missing" in result.error


class TestResolveMentions:
    def test_replaces_group_alias_with_native_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            mod, "_load_config", lambda: {"user_groups": {"@dev-team-fe": "<GROUP_TOKEN>"}}
        )
        assert mod.resolve_mentions("@dev-team-fe please review") == "<GROUP_TOKEN> please review"


class TestGetSaInfo:
    def test_parses_json_from_keyring(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            mod, "_keyring_lookup", lambda *, service, key: json.dumps({"client_email": "a@b"})
        )
        result = mod.get_sa_info()
        assert isinstance(result, SuccessResult)
        assert result.value["client_email"] == "a@b"

    def test_errors_when_secret_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_keyring_lookup", lambda *, service, key: None)
        result = mod.get_sa_info()
        assert isinstance(result, ErrorResult)
        assert "secret-tool" in result.error

    def test_errors_on_malformed_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_keyring_lookup", lambda *, service, key: "{not json")
        result = mod.get_sa_info()
        assert isinstance(result, ErrorResult)


class TestMintAccessToken:
    def test_signs_jwt_and_returns_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}

        def fake_encode(claims, key, algorithm):  # noqa: ANN001, ANN202
            captured["claims"] = claims
            captured["algorithm"] = algorithm
            return "signed.jwt.value"

        def fake_post_form(url, fields):  # noqa: ANN001, ANN202
            captured["url"] = url
            captured["fields"] = fields
            return ok({"access_token": "ya29.test", "expires_in": 3599})

        import jwt

        monkeypatch.setattr(jwt, "encode", fake_encode)
        monkeypatch.setattr(mod, "_post_form", fake_post_form)

        result = mod.mint_access_token(
            {"client_email": "bot@proj.iam", "private_key": "-----KEY-----"},
            now=1_000_000,
        )
        assert isinstance(result, SuccessResult)
        assert result.value == "ya29.test"
        assert captured["algorithm"] == "RS256"
        assert captured["claims"]["iss"] == "bot@proj.iam"
        assert captured["claims"]["scope"] == mod.GCHAT_SCOPE
        assert captured["claims"]["aud"] == mod.TOKEN_URI
        assert captured["claims"]["exp"] == 1_000_000 + 3600
        assert captured["fields"]["grant_type"] == mod._JWT_GRANT
        assert captured["fields"]["assertion"] == "signed.jwt.value"

    def test_propagates_token_endpoint_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import jwt

        monkeypatch.setattr(jwt, "encode", lambda *a, **k: "j")
        monkeypatch.setattr(mod, "_post_form", lambda url, fields: err("HTTP 400: invalid_grant"))
        result = mod.mint_access_token({"client_email": "x", "private_key": "k"}, now=1)
        assert isinstance(result, ErrorResult)
        assert "invalid_grant" in result.error

    def test_errors_when_response_lacks_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import jwt

        monkeypatch.setattr(jwt, "encode", lambda *a, **k: "j")
        monkeypatch.setattr(mod, "_post_form", lambda url, fields: ok({"expires_in": 1}))
        result = mod.mint_access_token({"client_email": "x", "private_key": "k"}, now=1)
        assert isinstance(result, ErrorResult)
