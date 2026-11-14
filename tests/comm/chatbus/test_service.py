from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from dev10x.domain.common.result import Result, err, ok

from dev10x.comm.chatbus import service
from dev10x.comm.chatbus.dispatch import HerdrLauncher
from dev10x.comm.chatbus.service import (
    CachedToken,
    ChatBusSettings,
    UnsentApprovalNotifier,
    build_ports,
    load_settings,
    merge_targets,
    parse_settings,
    target_provider,
    user_token,
)
from dev10x.comm.chatbus.sources.google_http import ChatRest, PubSubRest, WorkspaceEventsRest
from dev10x.comm.chatbus.sources.poll import WatchedSpace
from dev10x.comm.skills.notifications.gchat_watch import Watch
from tests.comm.chatbus.factories import NOW, expect_error, unwrap

CONFIG = Path("/config/gchat-config.yaml")
BOT = "users/500"
FULL: dict[str, Any] = {
    "chat_bus": {
        "bot_user": BOT,
        "spaces": ["spaces/TEAM"],
        "direct_messages": ["spaces/DM"],
        "pubsub": {
            "subscription": "projects/p/subscriptions/chat",
            "topic": "projects/p/topics/chat",
        },
        "dispatch": {"repo_root": "/work/repo"},
        "routes": {"spaces/TEAM": "web"},
    }
}


def _settings(**overrides: Any) -> ChatBusSettings:
    return unwrap(parse_settings(config={"chat_bus": {"bot_user": BOT, **overrides}}, path=CONFIG))


class TestParseSettings:
    def test_reads_every_field(self) -> None:
        assert unwrap(parse_settings(config=FULL, path=CONFIG)) == ChatBusSettings(
            bot_user=BOT,
            spaces=("spaces/TEAM",),
            direct_messages=("spaces/DM",),
            pubsub_subscription="projects/p/subscriptions/chat",
            pubsub_topic="projects/p/topics/chat",
            repo_root="/work/repo",
            routes={"spaces/TEAM": "web"},
        )

    def test_only_the_bot_user_is_required(self) -> None:
        assert _settings() == ChatBusSettings(bot_user=BOT)

    @pytest.mark.parametrize(
        ("config", "message"),
        [
            ({}, "No chat_bus: section"),
            ({"chat_bus": {}}, "bot_user must be"),
            ({"chat_bus": {"bot_user": "bot"}}, "bot_user must be"),
            ({"chat_bus": {"bot_user": BOT, "spaces": "spaces/A"}}, "chat_bus.spaces must"),
            ({"chat_bus": {"bot_user": BOT, "spaces": ["A"]}}, "chat_bus.spaces must"),
            ({"chat_bus": {"bot_user": BOT, "pubsub": "x"}}, "must be mappings"),
            (
                {"chat_bus": {"bot_user": BOT, "pubsub": {"subscription": ""}}},
                "chat_bus.pubsub.subscription must be a non-empty string",
            ),
            (
                {"chat_bus": {"bot_user": BOT, "pubsub": {"topic": "projects/p/topics/t"}}},
                "needs pubsub.subscription",
            ),
            (
                {"chat_bus": {"bot_user": BOT, "dispatch": {"repo_root": "work/repo"}}},
                "must be an absolute path",
            ),
        ],
    )
    def test_rejects_bad_config(self, config: dict[str, Any], message: str) -> None:
        assert message in expect_error(parse_settings(config=config, path=CONFIG)).error


class TestLoadSettings:
    def test_reads_the_yaml_file(self, tmp_path: Path) -> None:
        path = tmp_path / "gchat-config.yaml"
        path.write_text(f"chat_bus:\n  bot_user: {BOT}\n")
        assert unwrap(load_settings(path=path)) == ChatBusSettings(bot_user=BOT)

    def test_a_missing_file_is_an_error(self, tmp_path: Path) -> None:
        assert (
            "No Google Chat config"
            in expect_error(load_settings(path=tmp_path / "missing.yaml")).error
        )

    def test_invalid_yaml_is_an_error(self, tmp_path: Path) -> None:
        path = tmp_path / "gchat-config.yaml"
        path.write_text("chat_bus: [unclosed\n")
        assert "Cannot read the Google Chat config" in expect_error(load_settings(path=path)).error

    def test_a_non_mapping_document_has_no_section(self, tmp_path: Path) -> None:
        path = tmp_path / "gchat-config.yaml"
        path.write_text("- a list\n")
        assert "No chat_bus: section" in expect_error(load_settings(path=path)).error


class TestMergeTargets:
    def test_configured_spaces_are_read_whole_and_dms_flagged(self) -> None:
        settings = _settings(spaces=["spaces/TEAM"], direct_messages=["spaces/DM"])
        watched = [
            WatchedSpace(space="spaces/TEAM", threads=("spaces/TEAM/threads/t",)),
            WatchedSpace(space="spaces/OTHER", threads=("spaces/OTHER/threads/u",)),
        ]
        assert merge_targets(settings=settings, watched=watched) == [
            WatchedSpace(space="spaces/DM", direct_message=True),
            WatchedSpace(space="spaces/OTHER", threads=("spaces/OTHER/threads/u",)),
            WatchedSpace(space="spaces/TEAM"),
        ]


def _watch(*, space: str, expires_in: timedelta) -> Watch:
    return Watch(
        id=f"w-{space}",
        space=space,
        thread=None,
        notify=("me",),
        notify_roles=(),
        route=False,
        mode="ttl",
        armed_at=NOW - timedelta(hours=1),
        expires_at=NOW + expires_in,
    )


class TestTargetProvider:
    def test_adds_live_armed_watches(self) -> None:
        watches = [
            _watch(space="spaces/LIVE", expires_in=timedelta(hours=1)),
            _watch(space="spaces/GONE", expires_in=-timedelta(hours=1)),
        ]
        targets = target_provider(settings=_settings(), watches=lambda: ok(watches))
        assert targets(now=NOW) == [WatchedSpace(space="spaces/LIVE")]

    def test_unreadable_watches_fall_back_to_configured_spaces(self) -> None:
        targets = target_provider(
            settings=_settings(spaces=["spaces/TEAM"]), watches=lambda: err("corrupt json")
        )
        assert targets(now=NOW) == [WatchedSpace(space="spaces/TEAM")]


@dataclass
class Mint:
    results: list[Result[str]] = field(default_factory=lambda: [ok("t1"), ok("t2")])
    calls: int = 0

    def __call__(self) -> Result[str]:
        self.calls += 1
        return self.results.pop(0)


@dataclass
class Clock:
    now: datetime = NOW

    def __call__(self) -> datetime:
        return self.now


class TestCachedToken:
    def test_reuses_a_fresh_token(self) -> None:
        mint = Mint()
        token = CachedToken(mint=mint, clock=Clock())
        assert (unwrap(token()), unwrap(token()), mint.calls) == ("t1", "t1", 1)

    def test_mints_again_once_the_token_ages_out(self) -> None:
        mint, clock = Mint(), Clock()
        token = CachedToken(mint=mint, clock=clock)
        token()
        clock.now = NOW + timedelta(minutes=50)
        assert unwrap(token()) == "t2"

    def test_a_failed_mint_is_not_cached(self) -> None:
        mint = Mint(results=[err("refresh token revoked"), ok("t2")])
        token = CachedToken(mint=mint, clock=Clock())
        assert expect_error(token()).error == "refresh token revoked"
        assert unwrap(token()) == "t2"


class TestUserToken:
    def test_exchanges_the_adc_refresh_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[dict[str, str]] = []

        def mint_user_token(adc_info: dict[str, str]) -> Result[str]:
            seen.append(adc_info)
            return ok("user-token")

        monkeypatch.setattr(
            service.gchat_notify, "get_adc_info", lambda: ok({"type": "authorized_user"})
        )
        monkeypatch.setattr(service.gchat_notify, "mint_user_token", mint_user_token)
        assert unwrap(user_token()) == "user-token"
        assert seen == [{"type": "authorized_user"}]

    def test_missing_credentials_are_an_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(service.gchat_notify, "get_adc_info", lambda: err("No ADC"))
        assert expect_error(user_token()).error == "No ADC"


def test_approval_dms_are_not_sent_yet() -> None:
    sent = UnsentApprovalNotifier().request_approval(
        owner="users/1", work_item_id=7, requester="users/2", verb="start"
    )
    assert "`approve 7`" in expect_error(sent).error


class TestBuildPorts:
    def test_wires_every_configured_source(self) -> None:
        settings = unwrap(parse_settings(config=FULL, path=CONFIG))
        ports = build_ports(settings=settings, config_path=CONFIG, token=lambda: ok("t"))
        assert ports.pubsub is not None and ports.pubsub.renewal is not None
        assert isinstance(ports.pubsub.puller, PubSubRest)
        assert isinstance(ports.pubsub.renewal.api, WorkspaceEventsRest)
        assert ports.pubsub.renewal.spec.topic == "projects/p/topics/chat"
        assert isinstance(ports.history, ChatRest)
        assert ports.dispatching is not None
        assert isinstance(ports.dispatching.launcher, HerdrLauncher)
        assert ports.dispatching.config.routes == {"spaces/TEAM": "web"}
        assert ports.bot_user == BOT

    def test_leaves_out_what_is_not_configured(self) -> None:
        ports = build_ports(settings=_settings(), config_path=CONFIG, token=lambda: ok("t"))
        assert (ports.pubsub, ports.dispatching) == (None, None)
        assert isinstance(ports.notifier, UnsentApprovalNotifier)

    def test_pulls_without_renewing_when_no_topic_is_set(self) -> None:
        settings = _settings(pubsub={"subscription": "projects/p/subscriptions/chat"})
        ports = build_ports(settings=settings, config_path=CONFIG, token=lambda: ok("t"))
        assert ports.pubsub is not None and ports.pubsub.renewal is None

    def test_loads_the_allowlist_from_the_config_file(self, tmp_path: Path) -> None:
        path = tmp_path / "gchat-config.yaml"
        path.write_text(
            "users:\n  me:\n    chat_user_id: '1'\n    bus_role: owner\n"
            f"chat_bus:\n  bot_user: {BOT}\n"
        )
        ports = build_ports(settings=_settings(), config_path=path, token=lambda: ok("t"))
        assert unwrap(ports.load_allowlist(reason="start")).owner == "users/1"
