from __future__ import annotations

import pytest

from dev10x.domain.common.ticket_id import TICKET_ID_PATTERN, TicketId


class TestParse:
    @pytest.mark.parametrize(
        "raw,project,number",
        [
            ("GH-15", "GH", 15),
            ("PAY-133", "PAY", 133),
            ("TEAM-1", "TEAM", 1),
        ],
    )
    def test_parses_canonical_form(self, raw: str, project: str, number: int) -> None:
        ticket = TicketId.parse(raw)

        assert ticket.project == project
        assert ticket.number == number
        assert str(ticket) == raw

    @pytest.mark.parametrize(
        "raw",
        ["", "gh-15", "GH15", "GH-", "-15", "GH-12X", "GH-12-extra"],
    )
    def test_rejects_invalid_forms(self, raw: str) -> None:
        with pytest.raises(ValueError):
            TicketId.parse(raw)

    def test_rejects_non_string(self) -> None:
        with pytest.raises(ValueError):
            TicketId.parse(None)  # type: ignore[arg-type]


class TestTryParse:
    def test_returns_ticket_on_success(self) -> None:
        ticket = TicketId.try_parse("GH-1")

        assert ticket is not None
        assert ticket.number == 1

    def test_returns_none_on_failure(self) -> None:
        assert TicketId.try_parse("invalid") is None


class TestFindFirstInBranchName:
    @pytest.mark.parametrize(
        "branch,expected",
        [
            ("janusz/GH-12/slug", "GH-12"),
            ("janusz/GH-506/Dev10x-Claude-5/value-objects", "GH-506"),
            ("janusz/gh-12/slug", "GH-12"),
            ("PAY-133", "PAY-133"),
        ],
    )
    def test_extracts_segment_ticket(self, branch: str, expected: str) -> None:
        ticket = TicketId.find_first_in_branch_name(branch)

        assert ticket is not None
        assert str(ticket) == expected

    def test_returns_none_when_no_segment_ticket(self) -> None:
        assert TicketId.find_first_in_branch_name("janusz/just-a-slug") is None


class TestStripLeading:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("GH-12 Enable retries", "Enable retries"),
            ("PAY-133   Resolve timeout", "Resolve timeout"),
            ("Enable retries", "Enable retries"),
            ("GH-12-no-space", "GH-12-no-space"),
        ],
    )
    def test_strips_only_leading_ticket(self, text: str, expected: str) -> None:
        assert TicketId.strip_leading(text) == expected


def test_pattern_exposed_as_string() -> None:
    assert TICKET_ID_PATTERN == r"[A-Z]+-\d+"
