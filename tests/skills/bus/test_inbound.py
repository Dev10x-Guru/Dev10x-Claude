"""Tests for claude-bus inbound hygiene: size cap, expiry, duplicates, policy (GH-1624)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from dev10x.skills.bus.maildir import (
    MAX_BODY_CHARS,
    DuplicateFilter,
    Envelope,
    InboundPolicy,
    InvalidMessageError,
    classify,
    fingerprint,
    headers_for,
    is_expired,
    parse,
    read_message,
    send,
)

NOW = datetime(2026, 10, 18, 12, 0, 0, tzinfo=UTC)
LOOP = {"from": "kb-41", "subject": "ping"}


class TestBodyCap:
    def test_rejects_an_oversized_body(self, root: Path) -> None:
        with pytest.raises(InvalidMessageError, match="caps a message"):
            send(
                root=root,
                envelope=Envelope(sender="a", recipient="b", subject="s"),
                body="x" * (MAX_BODY_CHARS + 1),
            )

    def test_accepts_a_body_at_the_cap(self, root: Path) -> None:
        delivery = send(
            root=root,
            envelope=Envelope(sender="a", recipient="b", subject="s"),
            body="x" * MAX_BODY_CHARS,
        )

        assert delivery.path.is_file()


class TestExpiresHeader:
    def test_renders_iso_expiry(self) -> None:
        headers = headers_for(
            envelope=Envelope(sender="a", recipient="b", subject="s", expires=NOW),
            message_id="<1@h>",
            sent_at=NOW,
        )

        assert headers["Expires"] == "2026-10-18T12:00:00+00:00"

    def test_cannot_be_forged_as_an_extra_header(self) -> None:
        with pytest.raises(InvalidMessageError, match="set by the bus"):
            Envelope(sender="a", recipient="b", subject="s", extra_headers=(("Expires", "x"),))


class TestParse:
    def test_splits_headers_and_body(self) -> None:
        assert parse(text="---\nFrom: a\nSubject: Re: x\n---\n\nbody\n") == (
            {"from": "a", "subject": "Re: x"},
            "body\n",
        )

    @pytest.mark.parametrize("text", ["plain text", "---\nFrom: a\nno closing fence"])
    def test_text_without_frontmatter_is_all_body(self, text: str) -> None:
        assert parse(text=text) == ({}, text)

    def test_skips_lines_without_a_colon(self) -> None:
        assert parse(text="---\nnoise\nFrom: a\n---\n\nb")[0] == {"from": "a"}


class TestReadMessage:
    def test_reads_a_sent_message(self, root: Path) -> None:
        delivery = send(
            root=root, envelope=Envelope(sender="a", recipient="b", subject="s"), body="hi"
        )

        headers, body = read_message(message=delivery.path)

        assert (headers["from"], headers["message-id"], body) == (
            "a",
            delivery.message_id,
            "hi\n",
        )

    def test_missing_file_reads_empty(self, root: Path) -> None:
        assert read_message(message=root / "gone") == ({}, "")

    def test_binary_file_reads_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "bin"
        path.write_bytes(b"\xff\xfe\x00")

        assert read_message(message=path) == ({}, "")


class TestIsExpired:
    @pytest.mark.parametrize(
        ("headers", "expected"),
        [
            ({}, False),
            ({"expires": "not a date"}, False),
            ({"expires": "2026-10-18T11:59:00+00:00"}, True),
            ({"expires": "2026-10-18T12:00:00+00:00"}, True),
            ({"expires": "2026-10-18T12:01:00+00:00"}, False),
        ],
    )
    def test_compares_against_now(self, headers: dict[str, str], expected: bool) -> None:
        assert is_expired(headers=headers, now=NOW) is expected


class TestFingerprint:
    def test_ignores_surrounding_whitespace(self) -> None:
        assert fingerprint(headers=LOOP, body="hi\n") == fingerprint(headers=LOOP, body=" hi ")

    def test_changes_with_the_sender(self) -> None:
        assert fingerprint(headers=LOOP, body="hi") != fingerprint(
            headers={**LOOP, "from": "other"}, body="hi"
        )


class TestDuplicateFilter:
    @pytest.fixture
    def duplicates(self) -> DuplicateFilter:
        seen = DuplicateFilter()
        seen.repeats(key="k", now=NOW)
        return seen

    def test_first_sighting_is_not_a_repeat(self) -> None:
        assert not DuplicateFilter().repeats(key="k", now=NOW)

    def test_repeat_inside_the_window(self, duplicates: DuplicateFilter) -> None:
        assert duplicates.repeats(key="k", now=NOW + timedelta(seconds=30))

    def test_repeat_after_the_window_passes(self, duplicates: DuplicateFilter) -> None:
        assert not duplicates.repeats(key="k", now=NOW + timedelta(minutes=5))


class TestInboundPolicy:
    def test_rejects_a_bad_sender_name(self) -> None:
        with pytest.raises(InvalidMessageError, match="sender"):
            InboundPolicy(refuse=frozenset({"../x"}))


class TestClassify:
    @pytest.mark.parametrize(
        ("headers", "policy", "expected"),
        [
            (LOOP, InboundPolicy(), "NEW"),
            ({}, InboundPolicy(), "NEW"),
            (LOOP, InboundPolicy(refuse=frozenset({"kb-41"})), "REFUSED"),
            (LOOP, InboundPolicy(hold=frozenset({"kb-41"})), "HELD"),
            ({**LOOP, "expires": "2026-10-18T11:00:00+00:00"}, InboundPolicy(), "EXPIRED"),
            (
                {**LOOP, "expires": "2026-10-18T11:00:00+00:00"},
                InboundPolicy(refuse=frozenset({"kb-41"})),
                "REFUSED",
            ),
        ],
    )
    def test_first_message(
        self, headers: dict[str, str], policy: InboundPolicy, expected: str
    ) -> None:
        assert (
            classify(
                headers=headers,
                body="hi",
                policy=policy,
                duplicates=DuplicateFilter(),
                now=NOW,
            )
            == expected
        )

    @pytest.fixture
    def second_verdict(self) -> str:
        duplicates = DuplicateFilter()
        classify(headers=LOOP, body="hi", policy=InboundPolicy(), duplicates=duplicates, now=NOW)
        return classify(
            headers=LOOP, body="hi", policy=InboundPolicy(), duplicates=duplicates, now=NOW
        )

    def test_identical_repeat_is_dup(self, second_verdict: str) -> None:
        assert second_verdict == "DUP"

    def test_messages_without_a_sender_are_never_dup(self) -> None:
        duplicates = DuplicateFilter()
        classify(headers={}, body="", policy=InboundPolicy(), duplicates=duplicates, now=NOW)

        assert (
            classify(headers={}, body="", policy=InboundPolicy(), duplicates=duplicates, now=NOW)
            == "NEW"
        )
