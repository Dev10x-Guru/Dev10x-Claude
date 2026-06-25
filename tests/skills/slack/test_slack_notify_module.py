"""Tests for the importable slack_notify module (GH-442).

Mirrors the standalone-script test suite in test_slack_notify.py
to confirm the importable package module has identical behaviour.
"""

from __future__ import annotations

import pytest

from dev10x.domain.common.result import ErrorResult, ok
from dev10x.skills.notifications import slack_notify as mod


def _slack_api_error(error: str, **extra: object) -> Exception:
    """Build a SlackApiError whose response exposes ``error``/extra keys."""
    from slack_sdk.errors import SlackApiError

    return SlackApiError("boom", {"error": error, **extra})


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
        assert mod.get_token() == ok("xoxb-from-default-keyring")
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
        assert mod.get_token() == ok("xoxb-from-env")

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
        assert mod.get_token() == ok("xoxb-aperture")
        assert looked_up == ["slack-aperture"]

    def test_workspace_missing_token_returns_err(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(mod, "_keyring_lookup", lambda *, service, key: None)
        mod.set_workspace("aperture")
        result = mod.get_token()
        assert isinstance(result, ErrorResult)
        assert "aperture" in result.error

    def test_no_sources_returns_err(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(mod, "_keyring_lookup", lambda *, service, key: None)
        result = mod.get_token()
        assert isinstance(result, ErrorResult)
        assert "No Slack token found" in result.error

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
        assert mod.get_token() == ok("xoxb-aperture")
        assert looked_up == ["custom-aperture"]


class TestKeyringLookup:
    """GH-587: _keyring_lookup routes through subprocess_utils.run."""

    def test_returns_stripped_stdout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class FakeCompleted:
            stdout = "  xoxb-secret\n"

        monkeypatch.setattr(mod.subprocess_utils, "run", lambda *a, **k: FakeCompleted())
        assert mod._keyring_lookup(service="slack", key="bot_token") == "xoxb-secret"

    def test_returns_none_on_empty_stdout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class FakeCompleted:
            stdout = "   \n"

        monkeypatch.setattr(mod.subprocess_utils, "run", lambda *a, **k: FakeCompleted())
        assert mod._keyring_lookup(service="slack", key="bot_token") is None

    def test_returns_none_on_called_process_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import subprocess

        def boom(*a: object, **k: object):
            raise subprocess.CalledProcessError(returncode=1, cmd="lookup")

        monkeypatch.setattr(mod.subprocess_utils, "run", boom)
        assert mod._keyring_lookup(service="slack", key="bot_token") is None


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


class TestNotifySlack:
    """GH-587: notify_slack consolidates set_workspace + send behind one Result."""

    def test_selects_workspace_and_passes_through(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict = {}

        def fake_send(**kwargs: object):
            captured.update(kwargs)
            return ok("9.9")

        monkeypatch.setattr(mod, "send_slack_message", fake_send)
        result = mod.notify_slack(channel="C1", message="hi", workspace="aperture")
        assert result == ok("9.9")
        assert mod._active_workspace == "aperture"
        assert captured["channel"] == "C1"
        assert captured["message"] == "hi"

    def test_no_workspace_leaves_active_unchanged(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(mod, "send_slack_message", lambda **_: ok("1.0"))
        result = mod.notify_slack(channel="C1", message="hi")
        assert result == ok("1.0")
        assert mod._active_workspace is None


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


class TestUploadSlackFilesResult:
    """GH-533: upload_slack_files returns Result instead of print + None."""

    def test_returns_token_err(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_keyring_lookup", lambda *, service, key: None)
        result = mod.upload_slack_files(channel="C1", file_paths=[])
        assert isinstance(result, ErrorResult)
        assert "No Slack token found" in result.error

    def test_returns_err_when_file_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import slack_sdk

        monkeypatch.setenv("SLACK_TOKEN", "xoxb-test")
        monkeypatch.setattr(slack_sdk, "WebClient", lambda token: object())
        result = mod.upload_slack_files(channel="C1", file_paths=["/no/such/file"])
        assert isinstance(result, ErrorResult)
        assert "File not found" in result.error

    def test_returns_first_file_id(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        upload = tmp_path / "a.txt"
        upload.write_text("hi")
        captured: dict = {}

        class FakeClient:
            def __init__(self, token: str) -> None: ...

            def files_upload_v2(self, **kwargs: object) -> dict:
                captured.update(kwargs)
                return {"files": [{"id": "F1"}, {"id": "F2"}]}

        import slack_sdk

        monkeypatch.setenv("SLACK_TOKEN", "xoxb-test")
        monkeypatch.setattr(slack_sdk, "WebClient", FakeClient)
        result = mod.upload_slack_files(channel="C1", file_paths=[str(upload)], message="hey")
        assert result == ok("F1")
        assert captured["channel"] == "C1"

    def test_returns_ok_none_when_no_files(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        upload = tmp_path / "a.txt"
        upload.write_text("hi")

        class FakeClient:
            def __init__(self, token: str) -> None: ...

            def files_upload_v2(self, **kwargs: object) -> dict:
                return {"files": []}

        import slack_sdk

        monkeypatch.setenv("SLACK_TOKEN", "xoxb-test")
        monkeypatch.setattr(slack_sdk, "WebClient", FakeClient)
        result = mod.upload_slack_files(channel="C1", file_paths=[str(upload)])
        assert result == ok(None)

    def test_missing_scope_returns_err(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        upload = tmp_path / "a.txt"
        upload.write_text("hi")

        class FakeClient:
            def __init__(self, token: str) -> None: ...

            def files_upload_v2(self, **kwargs: object):
                raise _slack_api_error("missing_scope", needed="files:write")

        import slack_sdk

        monkeypatch.setenv("SLACK_TOKEN", "xoxb-test")
        monkeypatch.setattr(slack_sdk, "WebClient", FakeClient)
        result = mod.upload_slack_files(channel="C1", file_paths=[str(upload)])
        assert isinstance(result, ErrorResult)
        assert "files:write" in result.error

    def test_not_in_channel_autojoin_then_success(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        upload = tmp_path / "a.txt"
        upload.write_text("hi")
        calls = {"upload": 0, "join": 0}

        class FakeClient:
            def __init__(self, token: str) -> None: ...

            def files_upload_v2(self, **kwargs: object) -> dict:
                calls["upload"] += 1
                if calls["upload"] == 1:
                    raise _slack_api_error("not_in_channel")
                return {"files": [{"id": "F9"}]}

            def conversations_join(self, channel: str) -> None:
                calls["join"] += 1

        import slack_sdk

        monkeypatch.setenv("SLACK_TOKEN", "xoxb-test")
        monkeypatch.setattr(slack_sdk, "WebClient", FakeClient)
        result = mod.upload_slack_files(channel="C1", file_paths=[str(upload)])
        assert result == ok("F9")
        assert calls == {"upload": 2, "join": 1}

    def test_not_in_channel_autojoin_fails_returns_err(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        upload = tmp_path / "a.txt"
        upload.write_text("hi")

        class FakeClient:
            def __init__(self, token: str) -> None: ...

            def files_upload_v2(self, **kwargs: object):
                raise _slack_api_error("not_in_channel")

            def conversations_join(self, channel: str) -> None: ...

        import slack_sdk

        monkeypatch.setenv("SLACK_TOKEN", "xoxb-test")
        monkeypatch.setattr(slack_sdk, "WebClient", FakeClient)
        result = mod.upload_slack_files(channel="C1", file_paths=[str(upload)])
        assert isinstance(result, ErrorResult)
        assert "cannot auto-join" in result.error

    def test_generic_slack_error_returns_err(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        upload = tmp_path / "a.txt"
        upload.write_text("hi")

        class FakeClient:
            def __init__(self, token: str) -> None: ...

            def files_upload_v2(self, **kwargs: object):
                raise _slack_api_error("internal_error")

        import slack_sdk

        monkeypatch.setenv("SLACK_TOKEN", "xoxb-test")
        monkeypatch.setattr(slack_sdk, "WebClient", FakeClient)
        result = mod.upload_slack_files(channel="C1", file_paths=[str(upload)])
        assert isinstance(result, ErrorResult)
        assert "Failed to upload" in result.error


class TestSendReminderResult:
    """GH-533: send_reminder returns Result carrying the message ts."""

    def test_err_when_self_user_unconfigured(self) -> None:
        result = mod.send_reminder("ping")
        assert isinstance(result, ErrorResult)
        assert "self_user_id not configured" in result.error

    def test_err_when_token_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SLACK_SELF_USER_ID", "U1")
        monkeypatch.setattr(mod, "_keyring_lookup", lambda *, service, key: None)
        result = mod.send_reminder("ping")
        assert isinstance(result, ErrorResult)
        assert "No Slack token found" in result.error

    def test_ok_returns_ts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SLACK_SELF_USER_ID", "U1")
        monkeypatch.setenv("SLACK_TOKEN", "xoxb-test")

        class FakeClient:
            def __init__(self, token: str) -> None: ...

            def conversations_open(self, users: str) -> dict:
                return {"channel": {"id": "D1"}}

        import slack_sdk

        monkeypatch.setattr(slack_sdk, "WebClient", FakeClient)
        captured: dict = {}

        def fake_send(**kwargs: object):
            captured.update(kwargs)
            return ok("9.9")

        monkeypatch.setattr(mod, "send_slack_message", fake_send)
        result = mod.send_reminder("ping")
        assert result == ok("9.9")
        assert captured["channel"] == "D1"
        assert captured["message"] == "ping"

    def test_err_on_dm_open_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SLACK_SELF_USER_ID", "U1")
        monkeypatch.setenv("SLACK_TOKEN", "xoxb-test")

        class FakeClient:
            def __init__(self, token: str) -> None: ...

            def conversations_open(self, users: str):
                raise _slack_api_error("user_not_found")

        import slack_sdk

        monkeypatch.setattr(slack_sdk, "WebClient", FakeClient)
        result = mod.send_reminder("ping")
        assert isinstance(result, ErrorResult)
        assert "Failed to send reminder" in result.error


class TestUpdateSlackMessageResult:
    """GH-533: update_slack_message returns Result[None]."""

    def test_err_when_token_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_keyring_lookup", lambda *, service, key: None)
        result = mod.update_slack_message(channel="C1", ts="1.0", message="x")
        assert isinstance(result, ErrorResult)

    def test_ok_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class FakeClient:
            def __init__(self, token: str) -> None: ...

            def chat_update(self, **kwargs: object) -> dict:
                return {"ok": True}

        import slack_sdk

        monkeypatch.setenv("SLACK_TOKEN", "xoxb-test")
        monkeypatch.setattr(slack_sdk, "WebClient", FakeClient)
        assert mod.update_slack_message(channel="C1", ts="1.0", message="x") == ok(None)

    def test_err_on_slack_api_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class FakeClient:
            def __init__(self, token: str) -> None: ...

            def chat_update(self, **kwargs: object):
                raise _slack_api_error("message_not_found")

        import slack_sdk

        monkeypatch.setenv("SLACK_TOKEN", "xoxb-test")
        monkeypatch.setattr(slack_sdk, "WebClient", FakeClient)
        result = mod.update_slack_message(channel="C1", ts="1.0", message="x")
        assert isinstance(result, ErrorResult)
        assert "Failed to update" in result.error


class TestDeleteSlackMessageResult:
    """GH-533: delete_slack_message returns Result[None]."""

    def test_err_when_token_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_keyring_lookup", lambda *, service, key: None)
        result = mod.delete_slack_message(channel="C1", ts="1.0")
        assert isinstance(result, ErrorResult)

    def test_ok_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class FakeClient:
            def __init__(self, token: str) -> None: ...

            def chat_delete(self, **kwargs: object) -> dict:
                return {"ok": True}

        import slack_sdk

        monkeypatch.setenv("SLACK_TOKEN", "xoxb-test")
        monkeypatch.setattr(slack_sdk, "WebClient", FakeClient)
        assert mod.delete_slack_message(channel="C1", ts="1.0") == ok(None)

    def test_err_on_slack_api_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class FakeClient:
            def __init__(self, token: str) -> None: ...

            def chat_delete(self, **kwargs: object):
                raise _slack_api_error("message_not_found")

        import slack_sdk

        monkeypatch.setenv("SLACK_TOKEN", "xoxb-test")
        monkeypatch.setattr(slack_sdk, "WebClient", FakeClient)
        result = mod.delete_slack_message(channel="C1", ts="1.0")
        assert isinstance(result, ErrorResult)
        assert "Failed to delete Slack message" in result.error


class TestDeleteSlackFileResult:
    """GH-533: delete_slack_file returns Result[None]."""

    def test_err_when_token_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_keyring_lookup", lambda *, service, key: None)
        result = mod.delete_slack_file(file_id="F1")
        assert isinstance(result, ErrorResult)

    def test_ok_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class FakeClient:
            def __init__(self, token: str) -> None: ...

            def files_delete(self, **kwargs: object) -> dict:
                return {"ok": True}

        import slack_sdk

        monkeypatch.setenv("SLACK_TOKEN", "xoxb-test")
        monkeypatch.setattr(slack_sdk, "WebClient", FakeClient)
        assert mod.delete_slack_file(file_id="F1") == ok(None)

    def test_err_on_slack_api_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class FakeClient:
            def __init__(self, token: str) -> None: ...

            def files_delete(self, **kwargs: object):
                raise _slack_api_error("file_not_found")

        import slack_sdk

        monkeypatch.setenv("SLACK_TOKEN", "xoxb-test")
        monkeypatch.setattr(slack_sdk, "WebClient", FakeClient)
        result = mod.delete_slack_file(file_id="F1")
        assert isinstance(result, ErrorResult)
        assert "Failed to delete Slack file" in result.error
