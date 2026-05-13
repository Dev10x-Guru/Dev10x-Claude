"""Tests for slack-notify.py token resolution and workspace config (GH-98)."""

import importlib.util
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "slack_notify",
    _repo_root / "skills" / "slack" / "slack-notify.py",
)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


@pytest.fixture(autouse=True)
def reset_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure each test starts with no active workspace and empty config."""
    monkeypatch.setattr(_mod, "_config", {})
    monkeypatch.setattr(_mod, "_active_workspace", None)
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

        monkeypatch.setattr(_mod, "_keyring_lookup", fake_lookup)
        assert _mod.get_token() == "xoxb-from-default-keyring"
        assert calls == [{"service": "slack", "key": "bot_token"}]

    def test_env_var_wins_over_default_keyring(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SLACK_TOKEN", "xoxb-from-env")
        monkeypatch.setattr(
            _mod,
            "_keyring_lookup",
            lambda *, service, key: "xoxb-from-default-keyring",
        )
        assert _mod.get_token() == "xoxb-from-env"

    def test_workspace_uses_namespaced_keyring(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        looked_up: list[str] = []

        def fake_lookup(*, service: str, key: str) -> str | None:
            looked_up.append(service)
            return "xoxb-aperture" if service == "slack-aperture" else None

        monkeypatch.setattr(_mod, "_keyring_lookup", fake_lookup)
        _mod.set_workspace("aperture")
        assert _mod.get_token() == "xoxb-aperture"
        assert looked_up == ["slack-aperture"]

    def test_workspace_ignores_env_token(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SLACK_TOKEN", "xoxb-from-env")
        monkeypatch.setattr(
            _mod,
            "_keyring_lookup",
            lambda *, service, key: "xoxb-aperture",
        )
        _mod.set_workspace("aperture")
        assert _mod.get_token() == "xoxb-aperture"

    def test_workspace_missing_token_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(_mod, "_keyring_lookup", lambda *, service, key: None)
        _mod.set_workspace("aperture")
        with pytest.raises(RuntimeError, match="aperture"):
            _mod.get_token()

    def test_no_sources_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(_mod, "_keyring_lookup", lambda *, service, key: None)
        with pytest.raises(RuntimeError, match="No Slack token found"):
            _mod.get_token()

    def test_workspace_keyring_service_override(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            _mod,
            "_config",
            {"workspaces": {"aperture": {"keyring_service": "custom-aperture"}}},
        )
        looked_up: list[str] = []

        def fake_lookup(*, service: str, key: str) -> str | None:
            looked_up.append(service)
            return "xoxb-aperture"

        monkeypatch.setattr(_mod, "_keyring_lookup", fake_lookup)
        _mod.set_workspace("aperture")
        assert _mod.get_token() == "xoxb-aperture"
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
        monkeypatch.setattr(_mod, "_config", config)
        assert _mod._self_user_id() == "U_DEFAULT"
        assert _mod._bot_username() == "Default Bot"
        assert _mod._user_groups() == {"@default-team": "<!subteam^S_DEFAULT>"}

    def test_workspace_overrides_defaults(
        self,
        monkeypatch: pytest.MonkeyPatch,
        config: dict,
    ) -> None:
        monkeypatch.setattr(_mod, "_config", config)
        _mod.set_workspace("aperture")
        assert _mod._self_user_id() == "U_APERTURE"
        assert _mod._bot_username() == "Aperture Bot"
        assert _mod._user_groups() == {"@aperture-team": "<!subteam^S_APERTURE>"}

    def test_unknown_workspace_falls_back_to_defaults(
        self,
        monkeypatch: pytest.MonkeyPatch,
        config: dict,
    ) -> None:
        monkeypatch.setattr(_mod, "_config", config)
        _mod.set_workspace("ghost")
        assert _mod._bot_username() == "Default Bot"
        assert _mod._self_user_id() == "U_DEFAULT"

    def test_self_user_id_env_overrides_all(
        self,
        monkeypatch: pytest.MonkeyPatch,
        config: dict,
    ) -> None:
        monkeypatch.setattr(_mod, "_config", config)
        monkeypatch.setenv("SLACK_SELF_USER_ID", "U_FROM_ENV")
        _mod.set_workspace("aperture")
        assert _mod._self_user_id() == "U_FROM_ENV"


class TestResolveMentions:
    def test_uses_active_workspace_user_groups(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            _mod,
            "_config",
            {
                "user_groups": {"@default": "<!subteam^S_DEF>"},
                "workspaces": {
                    "aperture": {"user_groups": {"@aperture": "<!subteam^S_APE>"}},
                },
            },
        )
        _mod.set_workspace("aperture")
        assert _mod.resolve_mentions("ping @aperture") == "ping <!subteam^S_APE>"
        # default group not active when workspace is set
        assert _mod.resolve_mentions("ping @default") == "ping @default"
