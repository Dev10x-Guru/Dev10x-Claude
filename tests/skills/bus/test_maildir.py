"""Tests for the claude-bus Maildir primitives (GH-1516)."""

from __future__ import annotations

import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dev10x.skills.bus.maildir import (
    Delivery,
    Envelope,
    InvalidMessageError,
    done_targets,
    headers_for,
    is_unread_message,
    maildirs_for,
    mark_read,
    render,
    send,
    slugify,
    unread,
    validate_mailbox_name,
)

SENT_AT = datetime(2026, 10, 10, 10, 50, 22, tzinfo=UTC)


@pytest.fixture
def envelope() -> Envelope:
    return Envelope(sender="dev10x-7", recipient="kb-41", subject="Hello, World!")


@pytest.fixture
def delivery(root: Path, envelope: Envelope) -> Delivery:
    return send(root=root, envelope=envelope, body="ping\n\n", sent_at=SENT_AT)


@pytest.fixture
def delivered_text(delivery: Delivery) -> str:
    return delivery.path.read_text(encoding="utf-8")


class TestSend:
    def test_lands_in_recipient_new(self, root: Path, delivery: Delivery) -> None:
        assert delivery.path.parent == root / "kb-41" / "new"

    def test_leaves_no_draft_in_tmp(self, root: Path, delivery: Delivery) -> None:
        assert list((root / "kb-41" / "tmp").iterdir()) == []

    def test_creates_cur_for_readers(self, root: Path, delivery: Delivery) -> None:
        assert (root / "kb-41" / "cur").is_dir()

    def test_creates_private_root(self, root: Path, delivery: Delivery) -> None:
        assert stat.S_IMODE(root.stat().st_mode) == 0o700

    def test_names_file_by_stamp_sender_and_slug(self, delivery: Delivery) -> None:
        assert delivery.path.name.startswith("20261010T105022.")
        assert delivery.path.name.endswith(".dev10x-7.hello-world")

    def test_message_id_names_sender(self, delivery: Delivery) -> None:
        assert delivery.message_id.startswith("<20261010T105022.")
        assert ".dev10x-7@" in delivery.message_id

    def test_renders_frontmatter_then_body(self, delivered_text: str) -> None:
        assert delivered_text.startswith("---\nFrom: dev10x-7\nTo: kb-41\n")
        assert delivered_text.endswith("---\n\nping\n")

    def test_reply_to_defaults_to_sender(self, delivered_text: str) -> None:
        assert "Reply-To: dev10x-7\n" in delivered_text

    def test_omits_empty_headers(self, delivered_text: str) -> None:
        assert "In-Reply-To" not in delivered_text
        assert "Voice" not in delivered_text

    def test_thread_delivers_to_sorted_pair(self, root: Path, envelope: Envelope) -> None:
        result = send(root=root, envelope=envelope, body="x", thread=True, sent_at=SENT_AT)

        assert result.path.parent == root / "threads" / "dev10x-7--kb-41" / "new"

    def test_defaults_sent_at_to_now(self, root: Path, envelope: Envelope) -> None:
        result = send(root=root, envelope=envelope, body="x")

        assert result.path.is_file()


VALID_ENVELOPE = {"sender": "a", "recipient": "b", "subject": "s"}


class TestEnvelopeValidation:
    @pytest.mark.parametrize(
        ("overrides", "match"),
        [
            ({"recipient": "/etc"}, "recipient"),
            ({"recipient": "../x"}, "recipient"),
            ({"recipient": "a/b"}, "recipient"),
            ({"recipient": "a..b"}, "recipient"),
            ({"recipient": "a--b"}, "recipient"),
            ({"recipient": ".hidden"}, "recipient"),
            ({"recipient": ""}, "recipient"),
            ({"sender": "../a"}, "sender"),
            ({"reply_to": "../a"}, "reply_to"),
            ({"subject": "hi\nVoice: yes"}, "Subject"),
            ({"subject": "hi\r"}, "Subject"),
            ({"in_reply_to": "<1>\n"}, "In-Reply-To"),
            ({"references": "<1>\n"}, "References"),
            ({"extra_headers": (("Role", "x\ny"),)}, "Role"),
            ({"extra_headers": (("From", "c"),)}, "set by the bus"),
            ({"extra_headers": (("from", "c"),)}, "set by the bus"),
            ({"extra_headers": (("Bad Key", "v"),)}, "single token"),
        ],
    )
    def test_rejects(self, overrides: dict[str, object], match: str) -> None:
        with pytest.raises(InvalidMessageError, match=match):
            Envelope(**{**VALID_ENVELOPE, **overrides})

    @pytest.mark.parametrize(
        "name", ["registry", "cowork", "dev10x-claude-7-06", "kb_52", "a.b", "A1"]
    )
    def test_accepts_mailbox_name(self, name: str) -> None:
        validate_mailbox_name(field="recipient", value=name)


class TestHeadersFor:
    @pytest.fixture
    def headers(self) -> dict[str, str]:
        return headers_for(
            envelope=Envelope(
                sender="a",
                recipient="b",
                subject="s",
                reply_to="a-inbox",
                in_reply_to="<1@h>",
                voice=True,
                extra_headers=(("Role", "dev10x"),),
            ),
            message_id="<2@h>",
            sent_at=SENT_AT,
        )

    @pytest.mark.parametrize(
        ("key", "expected"),
        [
            ("Reply-To", "a-inbox"),
            ("In-Reply-To", "<1@h>"),
            ("References", "<1@h>"),
            ("Voice", "yes"),
            ("Role", "dev10x"),
            ("Date", "2026-10-10T10:50:22+00:00"),
        ],
    )
    def test_carries_header(self, headers: dict[str, str], key: str, expected: str) -> None:
        assert headers[key] == expected

    def test_explicit_references_win(self) -> None:
        headers = headers_for(
            envelope=Envelope(
                sender="a", recipient="b", subject="s", in_reply_to="<1@h>", references="<0@h>"
            ),
            message_id="<2@h>",
            sent_at=SENT_AT,
        )

        assert headers["References"] == "<0@h>"


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        ("Re: hello", "re-hello"),
        ("Zażółć gęślą", "za-g-l"),
        ("x" * 60, "x" * 40),
        ("--edge--", "edge"),
    ],
)
def test_slugify(subject: str, expected: str) -> None:
    assert slugify(subject=subject) == expected


def test_render_skips_empty_values() -> None:
    assert render(headers={"A": "1", "B": ""}, body="b") == "---\nA: 1\n---\n\nb\n"


class TestMaildirsFor:
    def test_rejects_name_outside_the_root(self, root: Path) -> None:
        with pytest.raises(InvalidMessageError, match="mailbox"):
            maildirs_for(root=root, name="../x")

    def test_only_own_when_no_threads(self, root: Path) -> None:
        assert maildirs_for(root=root, name="a") == [root / "a"]

    def test_includes_threads_naming_the_mailbox(self, root: Path) -> None:
        for pair in ("a--b", "b--c", "a--c"):
            (root / "threads" / pair).mkdir(parents=True)

        assert maildirs_for(root=root, name="a") == [
            root / "a",
            root / "threads" / "a--b",
            root / "threads" / "a--c",
        ]


class TestUnreadAndMarkRead:
    @pytest.fixture
    def message(self, root: Path) -> Path:
        new = root / "a" / "new"
        new.mkdir(parents=True)
        (new / "subdir").mkdir()
        path = new / "m1"
        path.write_text("x", encoding="utf-8")
        return path

    def test_unread_lists_files_only(self, root: Path, message: Path) -> None:
        assert unread(maildirs=[root / "a", root / "missing"]) == {message}

    def test_is_unread_message(self, message: Path) -> None:
        assert is_unread_message(message=message)

    def test_cur_file_is_not_unread(self, root: Path) -> None:
        assert not is_unread_message(message=root / "a" / "cur" / "m1")

    def test_mark_read_moves_to_cur_with_seen_flag(self, root: Path, message: Path) -> None:
        assert mark_read(message=message) == root / "a" / "cur" / "m1:2,S"


class TestDoneTargets:
    def test_mailbox_name_expands_to_new(self, root: Path) -> None:
        new = root / "a" / "new"
        new.mkdir(parents=True)
        (new / "m2").touch()
        (new / "m1").touch()

        assert done_targets(root=root, args=["a"]) == [new / "m1", new / "m2"]

    def test_absolute_paths_under_root_pass_through(self, root: Path) -> None:
        paths = [str(root / "a" / "new" / "m1"), str(root / "b" / "new" / "m2")]

        assert done_targets(root=root, args=paths) == [Path(path) for path in paths]

    def test_relative_path_resolves_against_root(self, root: Path) -> None:
        assert done_targets(root=root, args=["cowork/new/m1"]) == [root / "cowork/new/m1"]

    def test_each_mailbox_name_expands(self, root: Path) -> None:
        for name in ("a", "b"):
            (root / name / "new").mkdir(parents=True)
            (root / name / "new" / "m").touch()

        assert done_targets(root=root, args=["a", "b"]) == [
            root / "a" / "new" / "m",
            root / "b" / "new" / "m",
        ]

    @pytest.mark.parametrize("raw", ["/etc/new/passwd", "../outside/new/m"])
    def test_path_outside_root_is_an_error(self, root: Path, raw: str) -> None:
        with pytest.raises(InvalidMessageError, match="outside the bus root"):
            done_targets(root=root, args=[raw])

    def test_missing_mailbox_is_an_error(self, root: Path) -> None:
        with pytest.raises(InvalidMessageError, match="no new/"):
            done_targets(root=root, args=["nobody"])
