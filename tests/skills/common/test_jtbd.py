"""Tests for the shared JTBD/Slack helpers (GH-246 F5)."""

from __future__ import annotations

import pytest

from dev10x.skills.common.jtbd import (
    extract_jtbd,
    extract_jtbd_structured,
    md_to_slack_bold,
)

STRUCTURED_BODY = (
    "Some intro.\n\n"
    "**When** reconciling payments, **I want to** retry transient errors,"
    " **so I can** avoid manual reposting\n\n"
    "## Notes\nmore text"
)


class TestExtractJtbd:
    def test_collects_when_block_until_blank_line(self):
        body = "intro\n**When** X happens, I want Y\nso I can Z\n\ntrailing"
        assert extract_jtbd(body=body) == "**When** X happens, I want Y so I can Z"

    def test_stops_at_heading_line(self):
        body = "**When** X, I want Y\n# Heading\nignored"
        assert extract_jtbd(body=body) == "**When** X, I want Y"

    def test_returns_none_without_when_marker(self):
        assert extract_jtbd(body="no story here\njust text") is None

    def test_returns_none_on_empty_body(self):
        assert extract_jtbd(body="") is None


class TestExtractJtbdStructured:
    def test_matches_full_structured_story_and_adds_period(self):
        result = extract_jtbd_structured(body=STRUCTURED_BODY)
        assert result is not None
        assert result.startswith("**When** reconciling payments")
        assert result.endswith(".")
        assert "\n" not in result

    def test_keeps_existing_trailing_period(self):
        body = "**When** A, **I want to** B, **so I can** C."
        result = extract_jtbd_structured(body=body)
        assert result == "**When** A, **I want to** B, **so I can** C."

    @pytest.mark.parametrize(
        "body",
        [
            "",
            "no jtbd structure at all",
            "**When** X happens but no want clause",
        ],
    )
    def test_returns_none_when_structure_absent(self, body: str):
        assert extract_jtbd_structured(body=body) is None


class TestMdToSlackBold:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("**When** I do **this**", "*When* I do *this*"),
            ("plain text", "plain text"),
            ("", ""),
            ("**bold**", "*bold*"),
        ],
    )
    def test_converts_double_star_to_single(self, text: str, expected: str):
        assert md_to_slack_bold(text=text) == expected
