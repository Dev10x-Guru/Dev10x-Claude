"""Tests for the importable gchat_notify transport module."""

from __future__ import annotations

import json

import pytest

from dev10x.domain.common.result import ErrorResult, SuccessResult
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
