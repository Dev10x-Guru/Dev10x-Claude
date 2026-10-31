"""Route an inbound chat message to the session whose domain it belongs to (GH-1612).

A session announces its area of work on its registry ``hello`` with an
optional ``Domain`` header: ``short description: keyword, keyword``. A
dispatcher classifies each message deterministically — explicit address
first, then a configured space/thread map, then content — and leaves
anything ambiguous unrouted for the user, never answering by a guess.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dev10x.comm.skills.bus.maildir import read_message

REGISTRY_MAILBOX = "registry"
HELLO_SUBJECT = "hello"

REASON_EXPLICIT = "explicit"
REASON_MAP = "map"
REASON_CONTENT = "content"
REASON_AMBIGUOUS = "ambiguous"
REASON_NO_MATCH = "no-match"


@dataclass(frozen=True)
class Hello:
    role: str
    reply_to: str
    sent_at: datetime
    domain: str = ""
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class RouteDecision:
    role: str | None
    reason: str
    detail: str = ""

    @property
    def routed(self) -> bool:
        return self.role is not None


def parse_domain(raw: str) -> tuple[str, tuple[str, ...]]:
    description, colon, rest = raw.partition(":")
    listed = rest if colon else description
    keywords = tuple(word.strip().lower() for word in listed.split(",") if word.strip())
    return (description.strip() if colon else ""), keywords


def parse_hello(headers: Mapping[str, str]) -> Hello | None:
    role = headers.get("role", "").strip()
    reply_to = (headers.get("reply-to") or headers.get("from") or "").strip()
    if headers.get("subject", "").strip().lower() != HELLO_SUBJECT or not role or not reply_to:
        return None
    try:
        sent_at = datetime.fromisoformat(headers.get("date", ""))
    except ValueError:
        return None
    description, keywords = parse_domain(raw=headers.get("domain", ""))
    return Hello(
        role=role,
        reply_to=reply_to,
        sent_at=sent_at,
        domain=description,
        keywords=keywords,
    )


def newest_per_role(hellos: Iterable[Hello]) -> dict[str, Hello]:
    newest: dict[str, Hello] = {}
    for hello in hellos:
        current = newest.get(hello.role)
        if current is None or hello.sent_at > current.sent_at:
            newest[hello.role] = hello
    return newest


def read_registry(root: Path) -> dict[str, Hello]:
    registry = root / REGISTRY_MAILBOX
    files = [
        path
        for part in ("new", "cur")
        if (registry / part).is_dir()
        for path in sorted((registry / part).iterdir())
        if path.is_file()
    ]
    hellos = (parse_hello(headers=read_message(message=path)[0]) for path in files)
    return newest_per_role(hellos=(hello for hello in hellos if hello is not None))


def _mentions(*, text: str, term: str) -> bool:
    pattern = rf"(?<![\w-]){re.escape(term)}(?![\w-])"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def _explicit_roles(*, text: str, roles: Iterable[str]) -> list[str]:
    return sorted(role for role in roles if _mentions(text=text, term=role))


def _mapped_role(
    *,
    space: str,
    thread: str | None,
    routes: Mapping[str, str],
) -> str | None:
    if thread and thread in routes:
        return routes[thread]
    return routes.get(space)


def _content_roles(*, text: str, registry: Mapping[str, Hello]) -> list[str]:
    return sorted(
        role
        for role, hello in registry.items()
        if any(_mentions(text=text, term=keyword) for keyword in hello.keywords)
    )


def route_message(
    *,
    text: str,
    space: str,
    thread: str | None,
    registry: Mapping[str, Hello],
    routes: Mapping[str, str],
) -> RouteDecision:
    explicit = _explicit_roles(text=text, roles=set(registry) | set(routes.values()))
    if len(explicit) == 1:
        return RouteDecision(role=explicit[0], reason=REASON_EXPLICIT)
    if explicit:
        return RouteDecision(
            role=None, reason=REASON_AMBIGUOUS, detail=f"addresses {', '.join(explicit)}"
        )
    mapped = _mapped_role(space=space, thread=thread, routes=routes)
    if mapped:
        return RouteDecision(role=mapped, reason=REASON_MAP)
    matched = _content_roles(text=text, registry=registry)
    if len(matched) == 1:
        return RouteDecision(role=matched[0], reason=REASON_CONTENT)
    if matched:
        return RouteDecision(
            role=None, reason=REASON_AMBIGUOUS, detail=f"keywords of {', '.join(matched)}"
        )
    return RouteDecision(role=None, reason=REASON_NO_MATCH)
