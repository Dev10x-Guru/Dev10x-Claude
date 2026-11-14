"""Build the daemon's real adapters from the ``chat_bus:`` section of gchat-config.yaml.

Everything Google-facing reads the user's Application Default
Credentials (the grant ``gog`` and the Chat bot already use) through a
token provider, so the unit file carries no secret (ADR-0035 D9).
Nothing here runs at import time or in tests: tests build
``DaemonPorts`` from fakes and exercise the settings parsing only.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any, Protocol

import yaml

from dev10x.comm.chatbus.authz import load_allowlist
from dev10x.comm.chatbus.backfill import SubscriptionRecovery
from dev10x.comm.chatbus.daemon import (
    Clock,
    DaemonPorts,
    Dispatching,
    PollSource,
    PubSubSource,
    TargetProvider,
    utc_now,
)
from dev10x.comm.chatbus.dispatch import DispatchConfig, HerdrLauncher
from dev10x.comm.chatbus.sources.google_http import (
    ChatRest,
    GoogleJsonClient,
    PubSubRest,
    TokenProvider,
    WorkspaceEventsRest,
)
from dev10x.comm.chatbus.sources.poll import RawMessageReader, WatchedSpace, watched_from_watches
from dev10x.comm.chatbus.sources.pubsub import SubscriptionSpec
from dev10x.comm.skills.notifications import gchat_notify
from dev10x.comm.skills.notifications.gchat_watch import Watch, gog_list_messages, list_watches
from dev10x.domain.common.result import ErrorResult, Result, err, ok

log = logging.getLogger(__name__)

CONFIG_SECTION = "chat_bus"
TOKEN_LIFETIME = timedelta(minutes=50)
SPACE_PREFIX = "spaces/"


class WatchLister(Protocol):
    def __call__(self) -> Result[list[Watch]]: ...


@dataclass(frozen=True)
class ChatBusSettings:
    bot_user: str
    spaces: tuple[str, ...] = ()
    direct_messages: tuple[str, ...] = ()
    pubsub_subscription: str | None = None
    pubsub_topic: str | None = None
    repo_root: str | None = None
    routes: Mapping[str, str] = field(default_factory=dict)


def _names(*, section: Mapping[str, Any], key: str) -> Result[tuple[str, ...]]:
    raw = section.get(key) or []
    if not isinstance(raw, list) or not all(
        isinstance(name, str) and name.startswith(SPACE_PREFIX) for name in raw
    ):
        return err(f"{CONFIG_SECTION}.{key} must be a list of spaces/<id> names", key=key)
    return ok(tuple(raw))


def _optional_text(*, section: Mapping[str, Any], parent: str, key: str) -> Result[str | None]:
    raw = section.get(key)
    if raw is None or (isinstance(raw, str) and raw):
        return ok(raw)
    return err(f"{CONFIG_SECTION}.{parent}.{key} must be a non-empty string", key=key)


def parse_settings(*, config: Mapping[str, Any], path: Path) -> Result[ChatBusSettings]:
    section = config.get(CONFIG_SECTION)
    if not isinstance(section, Mapping):
        return err(f"No {CONFIG_SECTION}: section in {path}", path=str(path))
    bot_user = section.get("bot_user")
    if not isinstance(bot_user, str) or not bot_user.startswith("users/"):
        return err(f"{CONFIG_SECTION}.bot_user must be the bot's users/<id> in {path}")
    pubsub = section.get("pubsub") or {}
    dispatch = section.get("dispatch") or {}
    routes = section.get("routes") or {}
    if not all(isinstance(part, Mapping) for part in (pubsub, dispatch, routes)):
        return err(f"{CONFIG_SECTION}.pubsub, .dispatch and .routes must be mappings in {path}")
    fields: dict[str, Result[Any]] = {
        "spaces": _names(section=section, key="spaces"),
        "direct_messages": _names(section=section, key="direct_messages"),
        "pubsub_subscription": _optional_text(section=pubsub, parent="pubsub", key="subscription"),
        "pubsub_topic": _optional_text(section=pubsub, parent="pubsub", key="topic"),
        "repo_root": _optional_text(section=dispatch, parent="dispatch", key="repo_root"),
    }
    values: dict[str, Any] = {}
    for name, parsed in fields.items():
        if isinstance(parsed, ErrorResult):
            return parsed
        values[name] = parsed.value
    if values["pubsub_topic"] and not values["pubsub_subscription"]:
        return err(f"{CONFIG_SECTION}.pubsub.topic needs pubsub.subscription to pull from")
    if values["repo_root"] and not Path(values["repo_root"]).is_absolute():
        return err(f"{CONFIG_SECTION}.dispatch.repo_root must be an absolute path")
    return ok(
        ChatBusSettings(
            bot_user=bot_user,
            routes={str(key): str(value) for key, value in routes.items()},
            **values,
        )
    )


def load_settings(*, path: Path) -> Result[ChatBusSettings]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return err(f"No Google Chat config at {path}", path=str(path))
    except (OSError, yaml.YAMLError) as exc:
        log.error("Cannot read the Google Chat config at %s: %s", path, exc)
        return err(f"Cannot read the Google Chat config at {path}: {exc}", path=str(path))
    return parse_settings(config=raw if isinstance(raw, Mapping) else {}, path=path)


def merge_targets(
    *,
    settings: ChatBusSettings,
    watched: Sequence[WatchedSpace],
) -> list[WatchedSpace]:
    """Configured spaces and DMs are read whole; armed watches add their threads."""
    targets = {target.space: target for target in watched}
    for space in settings.spaces:
        targets[space] = WatchedSpace(space=space)
    for space in settings.direct_messages:
        targets[space] = WatchedSpace(space=space, direct_message=True)
    return sorted(targets.values(), key=lambda target: target.space)


@dataclass
class CachedToken:
    """Reuse one access token until shortly before it expires."""

    mint: TokenProvider
    clock: Clock = utc_now
    lifetime: timedelta = TOKEN_LIFETIME
    token: str | None = None
    expires: datetime | None = None

    def __call__(self) -> Result[str]:
        now = self.clock()
        if self.token is not None and self.expires is not None and now < self.expires:
            return ok(self.token)
        minted = self.mint()
        if isinstance(minted, ErrorResult):
            return minted
        self.token, self.expires = minted.value, now + self.lifetime
        return minted


def user_token() -> Result[str]:
    adc = gchat_notify.get_adc_info()
    if isinstance(adc, ErrorResult):
        return adc
    return gchat_notify.mint_user_token(adc_info=adc.value)


@dataclass(frozen=True)
class UnsentApprovalNotifier:
    """No approval DM goes out yet; the item waits in awaiting_approval."""

    # GH-1932

    def request_approval(
        self,
        *,
        owner: str,
        work_item_id: int,
        requester: str,
        verb: str,
    ) -> Result[str]:
        return err(
            f"Approval DMs are not sent yet; the owner approves work item {work_item_id} "
            f"with `approve {work_item_id}` in a DM with the bot",
            work_item_id=work_item_id,
        )


def target_provider(
    *,
    settings: ChatBusSettings,
    watches: WatchLister = list_watches,
) -> TargetProvider:
    def targets(*, now: datetime) -> list[WatchedSpace]:
        armed = watches()
        if isinstance(armed, ErrorResult):
            log.warning(
                "Armed Chat watches unreadable; reading configured spaces only: %s", armed.error
            )
            return merge_targets(settings=settings, watched=[])
        return merge_targets(
            settings=settings, watched=watched_from_watches(watches=armed.value, now=now)
        )

    return targets


def _pubsub(*, settings: ChatBusSettings, client: GoogleJsonClient) -> PubSubSource | None:
    if not settings.pubsub_subscription:
        return None
    topic = settings.pubsub_topic
    renewal = (
        None
        if topic is None
        else SubscriptionRecovery(
            api=WorkspaceEventsRest(client=client), spec=SubscriptionSpec(topic=topic)
        )
    )
    return PubSubSource(
        puller=PubSubRest(client=client),
        subscription=settings.pubsub_subscription,
        renewal=renewal,
    )


def _dispatching(*, settings: ChatBusSettings) -> Dispatching | None:
    if not settings.repo_root:
        return None
    return Dispatching(
        config=DispatchConfig(repo_root=settings.repo_root, routes=settings.routes),
        launcher=HerdrLauncher(repo_root=settings.repo_root),
    )


def build_ports(
    *,
    settings: ChatBusSettings,
    config_path: Path,
    token: TokenProvider,
    reader: RawMessageReader = gog_list_messages,
    watches: WatchLister = list_watches,
) -> DaemonPorts:
    client = GoogleJsonClient(token=token)
    return DaemonPorts(
        bot_user=settings.bot_user,
        notifier=UnsentApprovalNotifier(),
        load_allowlist=partial(load_allowlist, path=config_path),
        poll=PollSource(
            reader=reader, targets=target_provider(settings=settings, watches=watches)
        ),
        pubsub=_pubsub(settings=settings, client=client),
        history=ChatRest(client=client),
        dispatching=_dispatching(settings=settings),
    )
