"""Tests for slack-notify.py token resolution and workspace config (GH-98)."""

import importlib.util
import sys
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


class TestConfigHomeMatchesThePackageResolver:
    """GH-1045: pin the restated resolver to the one it claims to mirror.

    A standalone uv-script cannot import ``dev10x``, so ``_config_home``
    restates ``Dev10xConfigDir``'s root resolution by hand (the sanctioned
    Pattern 3 in ``references/code-sharing-patterns.md``). Hand-restated logic
    drifts: this copy had already lost the win32/APPDATA branch, which put
    ``slack-config.yaml`` in two places on Windows — the same
    two-statements-of-one-location defect GH-1045 exists to remove, and one
    the retired-path scanner cannot see because no retired path is named.

    The docstring says the copy "must stay faithful". This makes that a test
    rather than a promise, mirroring how GH-1041 pinned the protected-branch
    list to the shell script instead of restating it.
    """

    @staticmethod
    def _package_home() -> Path:
        from dev10x.domain.dev10x_paths import Dev10xConfigDir

        Dev10xConfigDir.reset_cache()
        return Dev10xConfigDir.home()

    def _assert_agree(self) -> None:
        assert _mod._config_home() == self._package_home()

    def test_explicit_override_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_CONFIG_HOME", "/srv/dev10x-config")
        self._assert_agree()

    def test_xdg_config_home(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEV10X_CONFIG_HOME", raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", "/srv/xdg")
        self._assert_agree()

    def test_bare_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEV10X_CONFIG_HOME", raising=False)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        self._assert_agree()

    def test_windows_appdata(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The branch whose absence produced the drift."""
        monkeypatch.delenv("DEV10X_CONFIG_HOME", raising=False)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setenv("APPDATA", r"C:\Users\dev\AppData\Roaming")
        # Pinned concretely so the parity assertion cannot pass vacuously: if
        # either side lost the branch it would answer ~/.config/Dev10x here.
        assert self._package_home() == Path(r"C:\Users\dev\AppData\Roaming") / "Dev10x"
        self._assert_agree()

    def test_windows_without_appdata_falls_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Why the win32 check nests instead of `and`-ing: it must fall through."""
        monkeypatch.delenv("DEV10X_CONFIG_HOME", raising=False)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.delenv("APPDATA", raising=False)
        self._assert_agree()
