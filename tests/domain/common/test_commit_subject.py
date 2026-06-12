from __future__ import annotations

import pytest

from dev10x.domain.common.commit_subject import CommitSubject
from dev10x.domain.common.ticket_id import TicketId


class TestParse:
    def test_parses_gitmoji_ticket_and_description(self) -> None:
        subject = CommitSubject.parse("♻️ GH-506 Unify plugin version parsing")

        assert subject.gitmoji == "♻️"
        assert subject.ticket == TicketId(project="GH", number=506)
        assert subject.description == "Unify plugin version parsing"

    def test_handles_missing_ticket(self) -> None:
        subject = CommitSubject.parse("✨ Add a brand new capability")

        assert subject.gitmoji == "✨"
        assert subject.ticket is None
        assert subject.description == "Add a brand new capability"

    def test_handles_missing_gitmoji(self) -> None:
        subject = CommitSubject.parse("PAY-133 Resolve the timeout")

        assert subject.gitmoji == ""
        assert subject.ticket == TicketId(project="PAY", number=133)
        assert subject.description == "Resolve the timeout"

    def test_plain_description_only(self) -> None:
        subject = CommitSubject.parse("Just a plain title")

        assert subject.gitmoji == ""
        assert subject.ticket is None
        assert subject.description == "Just a plain title"

    @pytest.mark.parametrize("title", ["", "   "])
    def test_empty_title(self, title: str) -> None:
        subject = CommitSubject.parse(title)

        assert subject.gitmoji == ""
        assert subject.ticket is None
        assert subject.description == ""
