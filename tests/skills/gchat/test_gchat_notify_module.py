"""Tests for the importable gchat_notify transport module."""

from __future__ import annotations

import io
import json
import subprocess
import urllib.error
from types import SimpleNamespace

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


class TestLoadConfig:
    def test_returns_parsed_yaml_when_file_present(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: object
    ) -> None:
        monkeypatch.setenv("DEV10X_CONFIG_HOME", str(tmp_path))
        config_path = tmp_path / "gchat-config.yaml"  # type: ignore[operator]
        config_path.write_text("spaces:\n  tt-reviews:\n    space_id: AAAA123\n")
        mod._config = None
        assert mod._load_config() == {"spaces": {"tt-reviews": {"space_id": "AAAA123"}}}
        assert mod._get_config() == {"spaces": {"tt-reviews": {"space_id": "AAAA123"}}}

    def test_returns_empty_dict_when_file_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: object
    ) -> None:
        monkeypatch.setenv("DEV10X_CONFIG_HOME", str(tmp_path))
        mod._config = None
        assert mod._load_config() == {}


class TestKeyringLookup:
    def test_returns_stripped_stdout_on_darwin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod.sys, "platform", "darwin")
        monkeypatch.setattr(
            mod.subprocess_utils, "run", lambda *a, **k: SimpleNamespace(stdout="val\n")
        )
        assert mod._keyring_lookup(service="gchat", key="sa_key") == "val"

    def test_returns_stripped_stdout_on_linux(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod.sys, "platform", "linux")
        monkeypatch.setattr(
            mod.subprocess_utils, "run", lambda *a, **k: SimpleNamespace(stdout="val\n")
        )
        assert mod._keyring_lookup(service="gchat", key="sa_key") == "val"

    def test_returns_none_on_called_process_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_run(*a, **k):  # noqa: ANN001, ANN202
            raise subprocess.CalledProcessError(1, "secret-tool")

        monkeypatch.setattr(mod.subprocess_utils, "run", fake_run)
        assert mod._keyring_lookup(service="gchat", key="sa_key") is None

    def test_returns_none_on_file_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_run(*a, **k):  # noqa: ANN001, ANN202
            raise FileNotFoundError

        monkeypatch.setattr(mod.subprocess_utils, "run", fake_run)
        assert mod._keyring_lookup(service="gchat", key="sa_key") is None


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

    def test_errors_on_missing_sa_info_field(self) -> None:
        result = mod.mint_access_token({"private_key": "x"}, now=1)
        assert isinstance(result, ErrorResult)
        assert "client_email" in result.error or "unusable for signing" in result.error

    def test_errors_when_jwt_encode_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import jwt

        def fake_encode(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise ValueError("bad key")

        monkeypatch.setattr(jwt, "encode", fake_encode)
        result = mod.mint_access_token(
            {"client_email": "bot@proj.iam", "private_key": "bad"}, now=1
        )
        assert isinstance(result, ErrorResult)
        assert "unusable for signing" in result.error


class TestGetAdcInfo:
    def test_reads_path_from_env_var(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: object
    ) -> None:
        adc_path = tmp_path / "adc.json"  # type: ignore[operator]
        adc_path.write_text('{"type": "authorized_user"}')
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(adc_path))
        result = mod.get_adc_info()
        assert isinstance(result, SuccessResult)
        assert result.value == {"type": "authorized_user"}

    def test_defaults_to_gcloud_well_known_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
        path = mod._adc_path()
        assert str(path).endswith(".config/gcloud/application_default_credentials.json")

    def test_errors_when_file_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: object
    ) -> None:
        monkeypatch.setenv(
            "GOOGLE_APPLICATION_CREDENTIALS",
            str(tmp_path / "absent.json"),  # type: ignore[operator]
        )
        result = mod.get_adc_info()
        assert isinstance(result, ErrorResult)
        assert "gcloud auth application-default login" in result.error

    def test_errors_on_malformed_json(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: object
    ) -> None:
        adc_path = tmp_path / "adc.json"  # type: ignore[operator]
        adc_path.write_text("{not json")
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(adc_path))
        result = mod.get_adc_info()
        assert isinstance(result, ErrorResult)
        assert "not valid JSON" in result.error


class TestMintUserToken:
    _ADC = {
        "type": "authorized_user",
        "client_id": "cid",
        "client_secret": "csec",
        "refresh_token": "rtok",
    }

    def test_exchanges_refresh_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}

        def fake_post_form(url, fields):  # noqa: ANN001, ANN202
            captured["url"] = url
            captured["fields"] = fields
            return ok({"access_token": "ya29.user"})

        monkeypatch.setattr(mod, "_post_form", fake_post_form)
        result = mod.mint_user_token(self._ADC)
        assert isinstance(result, SuccessResult)
        assert result.value == "ya29.user"
        assert captured["url"] == mod.TOKEN_URI
        assert captured["fields"]["grant_type"] == "refresh_token"
        assert captured["fields"]["refresh_token"] == "rtok"

    def test_errors_on_non_user_credentials(self) -> None:
        result = mod.mint_user_token({"type": "service_account"})
        assert isinstance(result, ErrorResult)
        assert "not user credentials" in result.error

    def test_errors_on_missing_field(self) -> None:
        result = mod.mint_user_token({"type": "authorized_user", "client_id": "cid"})
        assert isinstance(result, ErrorResult)
        assert "missing" in result.error

    def test_propagates_token_endpoint_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_post_form", lambda url, fields: err("HTTP 400: bad"))
        result = mod.mint_user_token(self._ADC)
        assert isinstance(result, ErrorResult)

    def test_errors_when_response_lacks_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_post_form", lambda url, fields: ok({"expires_in": 1}))
        result = mod.mint_user_token(self._ADC)
        assert isinstance(result, ErrorResult)


class TestMintImpersonatedToken:
    def test_posts_generate_access_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}

        def fake_post_json(url, payload, token, *, error_label):  # noqa: ANN001, ANN202
            captured.update(url=url, payload=payload, token=token, error_label=error_label)
            return ok({"accessToken": "ya29.sa"})

        monkeypatch.setattr(mod, "_post_json", fake_post_json)
        result = mod.mint_impersonated_token(
            service_account="bot@proj.iam.gserviceaccount.com", user_token="ya29.user"
        )
        assert isinstance(result, SuccessResult)
        assert result.value == "ya29.sa"
        assert captured["url"] == (
            f"{mod.IAM_CREDENTIALS_BASE}/projects/-/serviceAccounts/"
            "bot@proj.iam.gserviceaccount.com:generateAccessToken"
        )
        assert captured["payload"] == {"scope": [mod.GCHAT_SCOPE], "lifetime": "3600s"}
        assert captured["token"] == "ya29.user"
        assert "impersonation" in captured["error_label"]

    def test_propagates_post_json_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            mod, "_post_json", lambda url, payload, token, *, error_label: err("HTTP 403: denied")
        )
        result = mod.mint_impersonated_token(service_account="bot@p", user_token="t")
        assert isinstance(result, ErrorResult)
        assert "denied" in result.error

    def test_errors_when_response_lacks_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_post_json", lambda url, payload, token, *, error_label: ok({}))
        result = mod.mint_impersonated_token(service_account="bot@p", user_token="t")
        assert isinstance(result, ErrorResult)
        assert "accessToken" in result.error


class TestMintChatToken:
    def test_defaults_to_sa_key_method(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_load_config", lambda: {})
        monkeypatch.setattr(
            mod, "get_sa_info", lambda: ok({"client_email": "x", "private_key": "k"})
        )
        monkeypatch.setattr(mod, "mint_access_token", lambda info: ok("tok.sa_key"))
        result = mod.mint_chat_token()
        assert isinstance(result, SuccessResult)
        assert result.value == "tok.sa_key"

    def test_impersonate_method_chains_adc_user_and_sa_tokens(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            mod,
            "_load_config",
            lambda: {"auth": {"method": "impersonate", "service_account": "bot@p"}},
        )
        monkeypatch.setattr(mod, "get_adc_info", lambda: ok({"type": "authorized_user"}))
        monkeypatch.setattr(mod, "mint_user_token", lambda adc: ok("ya29.user"))
        captured: dict = {}

        def fake_impersonate(*, service_account, user_token):  # noqa: ANN001, ANN202
            captured.update(service_account=service_account, user_token=user_token)
            return ok("ya29.sa")

        monkeypatch.setattr(mod, "mint_impersonated_token", fake_impersonate)
        result = mod.mint_chat_token()
        assert isinstance(result, SuccessResult)
        assert result.value == "ya29.sa"
        assert captured == {"service_account": "bot@p", "user_token": "ya29.user"}

    def test_impersonate_requires_service_account(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_load_config", lambda: {"auth": {"method": "impersonate"}})
        result = mod.mint_chat_token()
        assert isinstance(result, ErrorResult)
        assert "auth.service_account" in result.error

    def test_errors_on_unknown_method(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_load_config", lambda: {"auth": {"method": "wif"}})
        result = mod.mint_chat_token()
        assert isinstance(result, ErrorResult)
        assert "wif" in result.error

    def test_short_circuits_on_adc_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            mod,
            "_load_config",
            lambda: {"auth": {"method": "impersonate", "service_account": "bot@p"}},
        )
        monkeypatch.setattr(mod, "get_adc_info", lambda: err("no adc"))
        result = mod.mint_chat_token()
        assert isinstance(result, ErrorResult)
        assert result.error == "no adc"

    def test_short_circuits_on_user_token_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            mod,
            "_load_config",
            lambda: {"auth": {"method": "impersonate", "service_account": "bot@p"}},
        )
        monkeypatch.setattr(mod, "get_adc_info", lambda: ok({"type": "authorized_user"}))
        monkeypatch.setattr(mod, "mint_user_token", lambda adc: err("no user token"))
        result = mod.mint_chat_token()
        assert isinstance(result, ErrorResult)
        assert result.error == "no user token"


class _FakeResponse:
    """Minimal context-manager stand-in for urllib.request.urlopen()'s return value."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class TestPostJson:
    def test_posts_and_parses_success_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            mod.urllib.request,
            "urlopen",
            lambda req, timeout=30: _FakeResponse(b'{"name": "spaces/A/messages/X"}'),
        )
        result = mod._post_json(f"{mod.CHAT_API_BASE}/spaces/A/messages", {"text": "hi"}, "tok")
        assert isinstance(result, SuccessResult)
        assert result.value == {"name": "spaces/A/messages/X"}

    def test_errors_on_http_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_urlopen(req, timeout=30):  # noqa: ANN001, ANN202
            raise urllib.error.HTTPError(
                "https://chat.googleapis.com/v1/spaces/A/messages",
                403,
                "Forbidden",
                hdrs=None,
                fp=io.BytesIO(b"denied"),
            )

        monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
        result = mod._post_json(f"{mod.CHAT_API_BASE}/spaces/A/messages", {"text": "hi"}, "tok")
        assert isinstance(result, ErrorResult)
        assert "403" in result.error
        assert "denied" in result.error

    def test_errors_on_url_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_urlopen(req, timeout=30):  # noqa: ANN001, ANN202
            raise urllib.error.URLError("boom")

        monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
        result = mod._post_json(f"{mod.CHAT_API_BASE}/spaces/A/messages", {"text": "hi"}, "tok")
        assert isinstance(result, ErrorResult)
        assert "boom" in result.error
        assert "chat.googleapis.com" in result.error

    def test_errors_use_custom_label(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_urlopen(req, timeout=30):  # noqa: ANN001, ANN202
            raise urllib.error.HTTPError(
                f"{mod.IAM_CREDENTIALS_BASE}/x",
                403,
                "Forbidden",
                hdrs=None,
                fp=io.BytesIO(b"denied"),
            )

        monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
        result = mod._post_json(
            f"{mod.IAM_CREDENTIALS_BASE}/x", {}, "tok", error_label="Impersonation failed"
        )
        assert isinstance(result, ErrorResult)
        assert result.error.startswith("Impersonation failed (HTTP 403)")


class TestPostForm:
    def test_posts_and_parses_success_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            mod.urllib.request,
            "urlopen",
            lambda req, timeout=30: _FakeResponse(b'{"access_token": "x"}'),
        )
        result = mod._post_form(mod.TOKEN_URI, {"grant_type": mod._JWT_GRANT, "assertion": "j"})
        assert isinstance(result, SuccessResult)
        assert result.value == {"access_token": "x"}

    def test_errors_on_http_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_urlopen(req, timeout=30):  # noqa: ANN001, ANN202
            raise urllib.error.HTTPError(
                mod.TOKEN_URI,
                400,
                "Bad Request",
                hdrs=None,
                fp=io.BytesIO(b"invalid_grant"),
            )

        monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
        result = mod._post_form(mod.TOKEN_URI, {"grant_type": mod._JWT_GRANT, "assertion": "j"})
        assert isinstance(result, ErrorResult)
        assert "400" in result.error
        assert "invalid_grant" in result.error

    def test_errors_on_url_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_urlopen(req, timeout=30):  # noqa: ANN001, ANN202
            raise urllib.error.URLError("down")

        monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
        result = mod._post_form(mod.TOKEN_URI, {"grant_type": mod._JWT_GRANT, "assertion": "j"})
        assert isinstance(result, ErrorResult)
        assert "down" in result.error


class TestBuildMessagePayload:
    def test_text_only_payload_is_unchanged(self) -> None:
        result = mod.build_message_payload(text="hi")
        assert isinstance(result, SuccessResult)
        assert result.value == {"text": "hi"}

    def test_cards_only_payload_omits_an_empty_fallback(self) -> None:
        # An empty fallbackText is no better than none — leave the key out.
        cards = [{"cardId": "c1", "card": {"sections": []}}]
        result = mod.build_message_payload(cards=cards)
        assert isinstance(result, SuccessResult)
        assert result.value == {"cardsV2": cards}

    def test_carries_text_and_cards_together(self) -> None:
        cards = [{"cardId": "c1", "card": {"sections": []}}]
        result = mod.build_message_payload(text="@team review", cards=cards)
        assert isinstance(result, SuccessResult)
        assert result.value["text"] == "@team review"
        assert result.value["cardsV2"] == cards

    def test_derives_fallback_text_from_message_markup(self) -> None:
        result = mod.build_message_payload(
            text="*Please review* [PR](https://example.com)",
            cards=[{"cardId": "c1", "card": {}}],
        )
        assert isinstance(result, SuccessResult)
        assert result.value["fallbackText"] == "Please review PR"

    def test_explicit_fallback_text_wins(self) -> None:
        result = mod.build_message_payload(
            text="hi", cards=[{"cardId": "c1", "card": {}}], fallback_text="override"
        )
        assert isinstance(result, SuccessResult)
        assert result.value["fallbackText"] == "override"

    def test_errors_when_neither_text_nor_cards_given(self) -> None:
        result = mod.build_message_payload()
        assert isinstance(result, ErrorResult)
        assert "text, cards, or both" in result.error


class TestPostMessage:
    def test_posts_json_and_returns_message_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}

        def fake_post_json(url, payload, token):  # noqa: ANN001, ANN202
            captured["url"] = url
            captured["payload"] = payload
            captured["token"] = token
            return ok({"name": "spaces/AAAA123/messages/XYZ"})

        monkeypatch.setattr(mod, "_post_json", fake_post_json)
        result = mod.post_message(space_id="AAAA123", text="hi", token="tok")
        assert isinstance(result, SuccessResult)
        assert result.value == "spaces/AAAA123/messages/XYZ"
        assert captured["url"] == f"{mod.CHAT_API_BASE}/spaces/AAAA123/messages"
        assert captured["payload"] == {"text": "hi"}
        assert captured["token"] == "tok"

    def test_posts_cards_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}
        cards = [{"cardId": "c1", "card": {"sections": []}}]

        def fake_post_json(url, payload, token):  # noqa: ANN001, ANN202
            captured["payload"] = payload
            return ok({"name": "spaces/AAAA123/messages/XYZ"})

        monkeypatch.setattr(mod, "_post_json", fake_post_json)
        result = mod.post_message(space_id="AAAA123", cards=cards, token="tok")
        assert isinstance(result, SuccessResult)
        assert captured["payload"]["cardsV2"] == cards

    def test_errors_before_posting_when_payload_is_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            mod,
            "_post_json",
            lambda *a, **k: pytest.fail("_post_json must not be reached"),
        )
        result = mod.post_message(space_id="AAAA123", token="tok")
        assert isinstance(result, ErrorResult)

    def test_errors_when_response_lacks_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_post_json", lambda url, payload, token: ok({}))
        result = mod.post_message(space_id="AAAA123", text="hi", token="tok")
        assert isinstance(result, ErrorResult)

    def test_propagates_post_json_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_post_json", lambda url, payload, token: err("boom"))
        result = mod.post_message(space_id="AAAA123", text="hi", token="tok")
        assert isinstance(result, ErrorResult)
        assert result.error == "boom"


class TestNotifyGchat:
    def _wire(self, monkeypatch: pytest.MonkeyPatch, captured: dict) -> None:
        monkeypatch.setattr(mod, "_load_config", lambda: {"user_groups": {"@team": "<GROUP>"}})
        monkeypatch.setattr(mod, "resolve_space_id", lambda alias: ok("AAAA123"))
        monkeypatch.setattr(
            mod, "get_sa_info", lambda: ok({"client_email": "x", "private_key": "k"})
        )
        monkeypatch.setattr(mod, "mint_access_token", lambda info: ok("tok"))

        def fake_post_message(  # noqa: ANN202
            *,
            space_id,  # noqa: ANN001
            token,  # noqa: ANN001
            text=None,  # noqa: ANN001
            cards=None,  # noqa: ANN001
            fallback_text=None,  # noqa: ANN001
        ):
            captured.update(
                space_id=space_id,
                text=text,
                token=token,
                cards=cards,
                fallback_text=fallback_text,
            )
            return ok("spaces/AAAA123/messages/XYZ")

        monkeypatch.setattr(mod, "post_message", fake_post_message)

    def test_resolves_and_posts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}
        self._wire(monkeypatch, captured)
        result = mod.notify_gchat(space="tt-reviews", message="@team please review")
        assert isinstance(result, SuccessResult)
        assert result.value == "spaces/AAAA123/messages/XYZ"
        assert captured["text"] == "<GROUP> please review"
        assert captured["space_id"] == "AAAA123"
        assert captured["cards"] is None

    def test_forwards_cards_and_resolves_mentions_in_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict = {}
        self._wire(monkeypatch, captured)
        cards = [{"cardId": "c1", "card": {"sections": []}}]
        result = mod.notify_gchat(
            space="tt-reviews", message="@team", cards=cards, fallback_text="@team review"
        )
        assert isinstance(result, SuccessResult)
        assert captured["cards"] == cards
        assert captured["fallback_text"] == "<GROUP> review"

    def test_cards_only_send_passes_no_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}
        self._wire(monkeypatch, captured)
        cards = [{"cardId": "c1", "card": {"sections": []}}]
        result = mod.notify_gchat(space="tt-reviews", cards=cards)
        assert isinstance(result, SuccessResult)
        assert captured["text"] is None
        assert captured["fallback_text"] is None

    def test_short_circuits_on_missing_space(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "resolve_space_id", lambda alias: err("no space"))
        result = mod.notify_gchat(space="bad", message="hi")
        assert isinstance(result, ErrorResult)
        assert result.error == "no space"

    def test_short_circuits_on_missing_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_load_config", lambda: {})
        monkeypatch.setattr(mod, "resolve_space_id", lambda alias: ok("AAAA123"))
        monkeypatch.setattr(mod, "get_sa_info", lambda: err("no key"))
        result = mod.notify_gchat(space="tt-reviews", message="hi")
        assert isinstance(result, ErrorResult)
        assert result.error == "no key"

    def test_short_circuits_on_mint_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_load_config", lambda: {})
        monkeypatch.setattr(mod, "resolve_space_id", lambda alias: ok("AAAA123"))
        monkeypatch.setattr(
            mod, "get_sa_info", lambda: ok({"client_email": "x", "private_key": "k"})
        )
        monkeypatch.setattr(mod, "mint_access_token", lambda info: err("no token"))
        monkeypatch.setattr(
            mod,
            "post_message",
            lambda **kwargs: pytest.fail("post_message must not be reached"),
        )
        result = mod.notify_gchat(space="tt-reviews", message="hi")
        assert isinstance(result, ErrorResult)
        assert result.error == "no token"
