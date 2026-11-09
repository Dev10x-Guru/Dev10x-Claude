"""Tests for the subagent status-line protocol parser (GH-248 G3)."""

from __future__ import annotations

import pytest
from dev10x.skills.orchestration.subagent_protocol import (
    BACKGROUND_DELIVERY_TEMPLATE,
    STATUS_PROMPT_TEMPLATE,
    ParsedStatus,
    SubagentStatus,
    is_hook_denial,
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
        ("result", "expected"),
        [
            ("DONE", False),
            ("DONE_WITH_CONCERNS: minor", False),
            ("NEEDS_CONTEXT: need ticket body", False),
            ("BLOCKED: gh auth expired", True),
            ("prose with no status line", True),
        ],
    )
    def test_fallback_only_for_blocked_and_malformed(self, result: str, expected: bool) -> None:
        parsed = parse_subagent_status(result=result)

        assert requires_main_session_fallback(parsed=parsed) is expected

    @pytest.mark.parametrize(
        "result",
        [
            "BLOCKED: hook denied git -C /wt push",
            "BLOCKED: Hook denied rm -rf build",
            "Blocked: hook denied git push",
        ],
    )
    def test_hook_denial_is_surfaced_not_rerun(self, result: str) -> None:
        parsed = parse_subagent_status(result=result)

        assert requires_main_session_fallback(parsed=parsed) is False


class TestIsHookDenial:
    @pytest.mark.parametrize(
        ("result", "expected"),
        [
            ("BLOCKED: hook denied git push", True),
            ("BLOCKED: the hook denied git push", True),
            ("BLOCKED: PreToolUse hook blocked git push", True),
            ("BLOCKED: git push was denied by a hook", True),
            ("BLOCKED: two hooks refused rm -rf build", True),
            ("BLOCKED hook denied git push", True),
            ("BLOCKED: webhook endpoint unreachable", False),
            ("BLOCKED: permission wall", False),
            ("NEEDS_CONTEXT: hook denied wording in prose", False),
            ("DONE_WITH_CONCERNS: a hook warned once", False),
        ],
    )
    def test_a_blocked_or_unreadable_hook_mention_counts(
        self, result: str, expected: bool
    ) -> None:
        parsed = parse_subagent_status(result=result)

        assert is_hook_denial(parsed=parsed) is expected


class TestStatusPromptTemplate:
    @pytest.mark.parametrize(
        "marker",
        ["DONE", "DONE_WITH_CONCERNS:", "NEEDS_CONTEXT:", "BLOCKED:", "BLOCKED: hook denied"],
    )
    def test_template_documents_every_status(self, marker: str):
        assert marker in STATUS_PROMPT_TEMPLATE


class TestBackgroundDeliveryTemplate:
    @pytest.mark.parametrize(
        "marker",
        ['SendMessage(to="main"', "idle notification", "LAST line", "Fallback"],
    )
    def test_template_documents_explicit_delivery(self, marker: str):
        # GH-776: named background agents must deliver via SendMessage,
        # not bare stdout.
        assert marker in BACKGROUND_DELIVERY_TEMPLATE

    def test_status_line_prefixes_present(self):
        for prefix in ("DONE", "NEEDS_CONTEXT", "BLOCKED"):
            assert prefix in BACKGROUND_DELIVERY_TEMPLATE


class TestParseSubagentStatusEdgeCases:
    def test_needs_context_does_not_require_fallback(self):
        parsed = parse_subagent_status(result="NEEDS_CONTEXT: need ticket body")
        assert requires_main_session_fallback(parsed=parsed) is False

    def test_done_with_concerns_does_not_require_fallback(self):
        parsed = parse_subagent_status(result="DONE_WITH_CONCERNS: minor style issues")
        assert requires_main_session_fallback(parsed=parsed) is False

    def test_colon_and_spaces_in_payload_are_preserved(self):
        parsed = parse_subagent_status(result="BLOCKED: gh auth: token expired")
        assert parsed.payload == "gh auth: token expired"

    def test_done_not_confused_with_done_with_concerns_prefix(self):
        # "DONE_WITH_CONCERNS" starts with "DONE" but must not parse as DONE.
        parsed = parse_subagent_status(result="DONE_WITH_CONCERNS: something")
        assert parsed.status == SubagentStatus.DONE_WITH_CONCERNS

    def test_status_line_buried_mid_output_is_ignored(self):
        # Only the LAST non-empty line counts as the status line.
        result = "BLOCKED: early signal\nsome follow-up prose\nDONE"
        parsed = parse_subagent_status(result=result)
        assert parsed.status == SubagentStatus.DONE

    def test_raw_line_is_preserved_for_debugging(self):
        parsed = parse_subagent_status(result="NEEDS_CONTEXT: re-check issue body")
        assert parsed.raw_line == "NEEDS_CONTEXT: re-check issue body"

    def test_malformed_carries_raw_line_for_debugging(self):
        parsed = parse_subagent_status(result="This is not a valid status")
        assert parsed.raw_line == "This is not a valid status"
        assert parsed.payload == ""
