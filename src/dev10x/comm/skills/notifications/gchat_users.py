"""The ``users:`` section of ``gchat-config.yaml`` and its ``bus_role`` field.

``bus_role`` is the Chat bus allowlist (ADR-0035 D3). Every malformed
entry or value parses to no authority, never to a guessed role.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from dev10x.domain.common.result import Result, err, ok

log = logging.getLogger(__name__)


class BusRole(StrEnum):
    OWNER = "owner"
    TRUSTED = "trusted"


_ROLE_VALUES = frozenset(role.value for role in BusRole)


@dataclass(frozen=True)
class ChatUser:
    login: str
    chat_user: str | None
    bus_role: BusRole | None


def chat_user_name(*, raw: object) -> str | None:
    value = str(raw).strip() if isinstance(raw, str | int) and not isinstance(raw, bool) else ""
    if not value.isascii():
        return None
    if value.isdigit():
        return f"users/{value}"
    if value.startswith("users/") and value.removeprefix("users/").isdigit():
        return value
    return None


def _bus_role(*, login: str, raw: object) -> BusRole | None:
    if raw is None:
        return None
    if isinstance(raw, str) and raw in _ROLE_VALUES:
        return BusRole(raw)
    log.warning("Ignoring invalid bus_role %r for Chat user %s: no authority", raw, login)
    return None


def _chat_user(*, login: str, entry: object) -> ChatUser:
    if not isinstance(entry, Mapping):
        log.warning("Chat user %s is not a mapping: no authority", login)
        return ChatUser(login=login, chat_user=None, bus_role=None)
    chat_user = chat_user_name(raw=entry.get("chat_user_id"))
    role = _bus_role(login=login, raw=entry.get("bus_role"))
    if role is not None and chat_user is None:
        log.warning("Chat user %s has a bus_role but no valid chat_user_id: no authority", login)
        role = None
    return ChatUser(login=login, chat_user=chat_user, bus_role=role)


def parse_chat_users(*, config: Mapping[str, Any]) -> tuple[ChatUser, ...]:
    users = config.get("users")
    if users is None:
        return ()
    if not isinstance(users, Mapping):
        log.warning("gchat-config.yaml users: is not a mapping: nobody has bus authority")
        return ()
    return tuple(_chat_user(login=str(login), entry=entry) for login, entry in users.items())


def load_chat_users(*, path: Path) -> Result[tuple[ChatUser, ...]]:
    try:
        raw = yaml.safe_load(path.read_text())
    except FileNotFoundError:
        return err(f"No Google Chat config at {path}", path=str(path))
    except (OSError, yaml.YAMLError) as exc:
        log.error("Cannot read the Google Chat config at %s: %s", path, exc)
        return err(f"Cannot read the Google Chat config at {path}: {exc}", path=str(path))
    if raw is None:
        return ok(())
    if not isinstance(raw, Mapping):
        return err(f"The Google Chat config at {path} is not a mapping", path=str(path))
    return ok(parse_chat_users(config=raw))
