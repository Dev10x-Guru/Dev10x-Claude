"""Tests for the importable slack_notify module (GH-442).

Mirrors the standalone-script test suite in test_slack_notify.py
to confirm the importable package module has identical behaviour.
"""

from __future__ import annotations

import pytest

from dev10x.domain.common.result import ErrorResult, ok
from dev10x.skills.notifications import slack_notify as mod


@pytest.fixture(autouse=True)
def reset_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset module-level state so tests are isolated."""
    monkeypatch.setattr(mod, "_config", {})
    monkeypatch.setattr(mod, "_active_workspace", None)
    monkeypatch.delenv("SLACK_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_SELF_USER_ID", raising=False)


class TestGetToken:
    def test_default_keyring_used_when_no_env_and_no_workspace(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[dict] = []

        def fake_lookup(*, service: str, key: str) -> str | None:
            calls.append({"service": service, "key": key})
            return "xoxb-from-default-keyring"

        monkeypatch.setattr(mod, "_keyring_lookup", fake_lookup)
        assert mod.get_token() == "xoxb-from-default-keyring"
        assert calls == [{"service": "slack", "key": "bot_token"}]

    def test_env_var_wins_over_default_keyring(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SLACK_TOKEN", "xoxb-from-env")
        monkeypatch.setattr(
            mod,
            "_keyring_lookup",
            lambda *, service, key: "xoxb-from-default-keyring",
        )
        assert mod.get_token() == "xoxb-from-env"

    def test_workspace_uses_namespaced_keyring(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        looked_up: list[str] = []

        def fake_lookup(*, service: str, key: str) -> str | None:
            looked_up.append(service)
            return "xoxb-aperture" if service == "slack-aperture" else None

        monkeypatch.setattr(mod, "_keyring_lookup", fake_lookup)
        mod.set_workspace("aperture")
        assert mod.get_token() == "xoxb-aperture"
        assert looked_up == ["slack-aperture"]

    def test_workspace_missing_token_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(mod, "_keyring_lookup", lambda *, service, key: None)
        mod.set_workspace("aperture")
        with pytest.raises(RuntimeError, match="aperture"):
            mod.get_token()

    def test_no_sources_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(mod, "_keyring_lookup", lambda *, service, key: None)
        with pytest.raises(RuntimeError, match="No Slack token found"):
            mod.get_token()

    def test_workspace_keyring_service_override(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            mod,
            "_config",
            {"workspaces": {"aperture": {"keyring_service": "custom-aperture"}}},
        )
        looked_up: list[str] = []

        def fake_lookup(*, service: str, key: str) -> str | None:
            looked_up.append(service)
            return "xoxb-aperture"

        monkeypatch.setattr(mod, "_keyring_lookup", fake_lookup)
        mod.set_workspace("aperture")
        assert mod.get_token() == "xoxb-aperture"
        assert looked_up == ["custom-aperture"]


class TestWorkspaceConfigResolution:
    @pytest.fixture()
    def config(self) -> dict:
        return {
            "self_user_id": "U_DEFAULT",
            "bot_username": "Default Bot",
            "user_groups": {"@default-team": "<!subteam^S_DEFAULT>"},
            "workspaces": {
                "aperture": {
                    "self_user_id": "U_APERTURE",
                    "bot_username": "Aperture Bot",
                    "user_groups": {"@aperture-team": "<!subteam^S_APERTURE>"},
                },
            },
        }

    def test_defaults_when_no_workspace(
        self,
        monkeypatch: pytest.MonkeyPatch,
        config: dict,
    ) -> None:
        monkeypatch.setattr(mod, "_config", config)
        assert mod._self_user_id() == "U_DEFAULT"
        assert mod._bot_username() == "Default Bot"
        assert mod._user_groups() == {"@default-team": "<!subteam^S_DEFAULT>"}

    def test_workspace_overrides_defaults(
        self,
        monkeypatch: pytest.MonkeyPatch,
        config: dict,
    ) -> None:
        monkeypatch.setattr(mod, "_config", config)
        mod.set_workspace("aperture")
        assert mod._self_user_id() == "U_APERTURE"
        assert mod._bot_username() == "Aperture Bot"
        assert mod._user_groups() == {"@aperture-team": "<!subteam^S_APERTURE>"}

    def test_unknown_workspace_falls_back_to_defaults(
        self,
        monkeypatch: pytest.MonkeyPatch,
        config: dict,
    ) -> None:
        monkeypatch.setattr(mod, "_config", config)
        mod.set_workspace("ghost")
        assert mod._bot_username() == "Default Bot"
        assert mod._self_user_id() == "U_DEFAULT"

    def test_self_user_id_env_overrides_all(
        self,
        monkeypatch: pytest.MonkeyPatch,
        config: dict,
    ) -> None:
        monkeypatch.setattr(mod, "_config", config)
        monkeypatch.setenv("SLACK_SELF_USER_ID", "U_FROM_ENV")
        mod.set_workspace("aperture")
        assert mod._self_user_id() == "U_FROM_ENV"


class TestResolveMentions:
    def test_uses_active_workspace_user_groups(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            mod,
            "_config",
            {
                "user_groups": {"@default": "<!subteam^S_DEF>"},
                "workspaces": {
                    "aperture": {"user_groups": {"@aperture": "<!subteam^S_APE>"}},
                },
            },
        )
        mod.set_workspace("aperture")
        assert mod.resolve_mentions("ping @aperture") == "ping <!subteam^S_APE>"
        assert mod.resolve_mentions("ping @default") == "ping @default"


class TestSendSlackMessageResult:
    """GH-537: send_slack_message returns Result[str] instead of swallowing errors."""

    def test_returns_err_when_token_lookup_fails(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr(mod, "_keyring_lookup", lambda *, service, key: None)
        with caplog.at_level("ERROR", logger="dev10x.skills.notifications.slack_notify"):
            result = mod.send_slack_message(channel="C123", message="hi")
        assert isinstance(result, ErrorResult)
        assert "No Slack token found" in result.error
        assert "Failed to send Slack message" in caplog.text

    def test_returns_ok_with_ts_on_success(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class FakeClient:
            def __init__(self, token: str) -> None:
                self.token = token

            def chat_postMessage(self, **kwargs: object) -> dict:
                return {"ts": "1234.5678"}

        import slack_sdk

        monkeypatch.setenv("SLACK_TOKEN", "xoxb-test")
        monkeypatch.setattr(slack_sdk, "WebClient", FakeClient)
        result = mod.send_slack_message(channel="C123", message="hi")
        assert result == ok("1234.5678")

    def test_programming_errors_propagate(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """KeyError and friends must NOT be swallowed (GH-537 AC)."""

        class BrokenClient:
            def __init__(self, token: str) -> None:
                self.token = token

            def chat_postMessage(self, **kwargs: object) -> dict:
                return {}  # missing "ts" → KeyError in the happy path

        import slack_sdk

        monkeypatch.setenv("SLACK_TOKEN", "xoxb-test")
        monkeypatch.setattr(slack_sdk, "WebClient", BrokenClient)
        with pytest.raises(KeyError):
            mod.send_slack_message(channel="C123", message="hi")


class TestUvxEnvImportSmoke:
    """GH-483: the in-process slack notify path must have slack_sdk available.

    `uvx dev10x skill notify slack-send` imports slack_sdk inside
    slack_notify.py. slack-sdk is declared as a base dependency so the
    uvx-distributed env provisions it; this smoke test fails loudly if
    that dependency is ever dropped from pyproject.
    """

    def test_slack_sdk_importable(self) -> None:
        import importlib

        assert importlib.import_module("slack_sdk") is not None

    def test_webclient_importable_for_send_path(self) -> None:
        # Mirrors the exact import inside slack_notify.send_slack_message.
        from slack_sdk import WebClient

        assert WebClient is not None
