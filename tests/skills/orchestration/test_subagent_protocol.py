"""Tests for the subagent status-line protocol parser (GH-248 G3)."""

from __future__ import annotations

import pytest

from dev10x.skills.orchestration.subagent_protocol import (
    STATUS_PROMPT_TEMPLATE,
    ParsedStatus,
    SubagentStatus,
    parse_subagent_status,
    requires_main_session_fallback,
)


class TestParseSubagentStatus:
    @pytest.mark.parametrize(
        ("result", "expected_status", "expected_payload"),
        [
            ("DONE", SubagentStatus.DONE, ""),
            (
                "DONE_WITH_CONCERNS: tests skipped",
                SubagentStatus.DONE_WITH_CONCERNS,
                "tests skipped",
            ),
            (
                "NEEDS_CONTEXT: corrected ticket id",
                SubagentStatus.NEEDS_CONTEXT,
                "corrected ticket id",
            ),
            ("BLOCKED: gh auth error", SubagentStatus.BLOCKED, "gh auth error"),
        ],
    )
    def test_each_status_prefix(
        self,
        result: str,
        expected_status: SubagentStatus,
        expected_payload: str,
    ):
        parsed = parse_subagent_status(result=result)
        assert parsed.status == expected_status
        assert parsed.payload == expected_payload

    def test_last_non_empty_line_wins(self):
        result = "fetched the ticket\nsummary line\n\nBLOCKED: MCP unavailable\n\n"
        parsed = parse_subagent_status(result=result)
        assert parsed.status == SubagentStatus.BLOCKED
        assert parsed.payload == "MCP unavailable"

    def test_trailing_whitespace_on_done_is_tolerated(self):
        parsed = parse_subagent_status(result="work summary\n   DONE   ")
        assert parsed.status == SubagentStatus.DONE
        assert parsed.raw_line == "DONE"

    @pytest.mark.parametrize(
        "result",
        [
            "",
            "   \n\n  ",
            "all done, no status line",
            "DONEISH",
            "DONE_WITH_CONCERNS no colon",
            "blocked: lowercase prefix",
        ],
    )
    def test_missing_or_unrecognized_line_is_malformed(self, result: str):
        parsed = parse_subagent_status(result=result)
        assert parsed.status == SubagentStatus.MALFORMED
        assert parsed.payload == ""

    def test_payload_whitespace_is_stripped(self):
        parsed = parse_subagent_status(result="DONE_WITH_CONCERNS:   spaced   ")
        assert parsed.payload == "spaced"

    def test_empty_payload_after_prefix(self):
        parsed = parse_subagent_status(result="BLOCKED:")
        assert parsed.status == SubagentStatus.BLOCKED
        assert parsed.payload == ""

    def test_returns_parsed_status_instance(self):
        parsed = parse_subagent_status(result="DONE")
        assert isinstance(parsed, ParsedStatus)


class TestRequiresMainSessionFallback:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (SubagentStatus.DONE, False),
            (SubagentStatus.DONE_WITH_CONCERNS, False),
            (SubagentStatus.NEEDS_CONTEXT, False),
            (SubagentStatus.BLOCKED, True),
            (SubagentStatus.MALFORMED, True),
        ],
    )
    def test_fallback_only_for_blocked_and_malformed(
        self,
        status: SubagentStatus,
        expected: bool,
    ):
        assert requires_main_session_fallback(status=status) is expected


class TestStatusPromptTemplate:
    @pytest.mark.parametrize(
        "marker",
        ["DONE", "DONE_WITH_CONCERNS:", "NEEDS_CONTEXT:", "BLOCKED:"],
    )
    def test_template_documents_every_status(self, marker: str):
        assert marker in STATUS_PROMPT_TEMPLATE
