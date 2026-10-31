from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from dev10x.comm.skills.bus.maildir import Envelope, mark_read, send
from dev10x.comm.skills.bus.routing import (
    REASON_AMBIGUOUS,
    REASON_CONTENT,
    REASON_EXPLICIT,
    REASON_MAP,
    REASON_NO_MATCH,
    Hello,
    RouteDecision,
    newest_per_role,
    parse_domain,
    parse_hello,
    read_registry,
    route_message,
)

EARLY = datetime.fromisoformat("2026-10-30T10:00:00+00:00")
LATE = datetime.fromisoformat("2026-10-30T11:00:00+00:00")


def hello(*, role: str, reply_to: str, keywords: tuple[str, ...] = ()) -> Hello:
    return Hello(role=role, reply_to=reply_to, sent_at=EARLY, keywords=keywords)


@pytest.fixture
def registry() -> dict[str, Hello]:
    return {
        "bl-gymos": hello(
            role="bl-gymos", reply_to="gym-1", keywords=("gymos", "schedules", "memberships")
        ),
        "tt-backend": hello(role="tt-backend", reply_to="tt-3", keywords=("invoice", "orders")),
    }


class TestParseDomain:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("GymOS app: schedules, Memberships", ("GymOS app", ("schedules", "memberships"))),
            ("schedules, memberships", ("", ("schedules", "memberships"))),
            ("", ("", ())),
            ("app: , ,x", ("app", ("x",))),
        ],
    )
    def test_splits_description_and_keywords(
        self, raw: str, expected: tuple[str, tuple[str, ...]]
    ) -> None:
        assert parse_domain(raw=raw) == expected


class TestParseHello:
    def test_reads_role_reply_to_and_domain(self) -> None:
        headers = {
            "subject": "hello",
            "role": "bl-gymos",
            "reply-to": "gym-1",
            "date": "2026-10-30T10:00:00+00:00",
            "domain": "GymOS: schedules",
        }

        assert parse_hello(headers=headers) == Hello(
            role="bl-gymos",
            reply_to="gym-1",
            sent_at=EARLY,
            domain="GymOS",
            keywords=("schedules",),
        )

    def test_falls_back_to_from_for_reply_to(self) -> None:
        headers = {"subject": "hello", "role": "r", "from": "a", "date": EARLY.isoformat()}

        parsed = parse_hello(headers=headers)

        assert parsed is not None
        assert parsed.reply_to == "a"

    @pytest.mark.parametrize(
        "headers",
        [
            {"subject": "status", "role": "r", "reply-to": "a", "date": "2026-10-30T10:00:00"},
            {"subject": "hello", "reply-to": "a", "date": "2026-10-30T10:00:00"},
            {"subject": "hello", "role": "r", "date": "2026-10-30T10:00:00"},
            {"subject": "hello", "role": "r", "reply-to": "a", "date": "yesterday"},
        ],
    )
    def test_rejects_non_hellos_and_incomplete_ones(self, headers: dict[str, str]) -> None:
        assert parse_hello(headers=headers) is None


def test_newest_per_role_keeps_the_latest_hello() -> None:
    old = Hello(role="r", reply_to="old", sent_at=EARLY)
    new = Hello(role="r", reply_to="new", sent_at=LATE)

    assert newest_per_role(hellos=[new, old]) == {"r": new}


class TestReadRegistry:
    def _hello(self, *, root: Path, mailbox: str, sent_at: datetime) -> Path:
        return send(
            root=root,
            envelope=Envelope(
                sender=mailbox,
                recipient="registry",
                subject="hello",
                reply_to=mailbox,
                extra_headers=(("Role", "tt-backend"), ("Domain", "TT: invoice")),
            ),
            body="hi",
            sent_at=sent_at,
        ).path

    def test_reads_new_and_cur_and_keeps_the_newest(self, root: Path) -> None:
        mark_read(message=self._hello(root=root, mailbox="tt-old", sent_at=EARLY))
        self._hello(root=root, mailbox="tt-new", sent_at=LATE)

        registry = read_registry(root=root)

        assert registry["tt-backend"].reply_to == "tt-new"
        assert registry["tt-backend"].keywords == ("invoice",)

    def test_an_absent_registry_is_empty(self, root: Path) -> None:
        assert read_registry(root=root) == {}


class TestRouteMessage:
    @pytest.mark.parametrize(
        ("text", "thread", "routes", "expected"),
        [
            (
                "for tt-backend: the invoice total is off",
                None,
                {},
                RouteDecision(role="tt-backend", reason=REASON_EXPLICIT),
            ),
            (
                "@bl-gymos please look",
                None,
                {"spaces/A": "tt-backend"},
                RouteDecision(role="bl-gymos", reason=REASON_EXPLICIT),
            ),
            (
                "bl-gymos and tt-backend both?",
                None,
                {},
                RouteDecision(
                    role=None, reason=REASON_AMBIGUOUS, detail="addresses bl-gymos, tt-backend"
                ),
            ),
            (
                "anything",
                "spaces/A/threads/T",
                {"spaces/A/threads/T": "bl-gymos", "spaces/A": "tt-backend"},
                RouteDecision(role="bl-gymos", reason=REASON_MAP),
            ),
            (
                "anything",
                "spaces/A/threads/T",
                {"spaces/A": "tt-backend"},
                RouteDecision(role="tt-backend", reason=REASON_MAP),
            ),
            (
                "The new Schedules page is blank",
                None,
                {},
                RouteDecision(role="bl-gymos", reason=REASON_CONTENT),
            ),
            (
                "schedules for invoice orders",
                None,
                {},
                RouteDecision(
                    role=None, reason=REASON_AMBIGUOUS, detail="keywords of bl-gymos, tt-backend"
                ),
            ),
            (
                "lunch anyone?",
                None,
                {},
                RouteDecision(role=None, reason=REASON_NO_MATCH),
            ),
            (
                "rescheduleschedules-ish",
                None,
                {},
                RouteDecision(role=None, reason=REASON_NO_MATCH),
            ),
        ],
    )
    def test_applies_explicit_then_map_then_content(
        self,
        registry: dict[str, Hello],
        text: str,
        thread: str | None,
        routes: dict[str, str],
        expected: RouteDecision,
    ) -> None:
        decision = route_message(
            text=text, space="spaces/A", thread=thread, registry=registry, routes=routes
        )

        assert decision == expected

    @pytest.mark.parametrize(
        ("decision", "routed"),
        [
            (RouteDecision(role="r", reason=REASON_MAP), True),
            (RouteDecision(role=None, reason=REASON_NO_MATCH), False),
        ],
    )
    def test_routed_reflects_the_role(self, decision: RouteDecision, routed: bool) -> None:
        assert decision.routed is routed
