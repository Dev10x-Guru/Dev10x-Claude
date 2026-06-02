"""Tests for the Dev10x MCP knowledge prompts (GH-340).

Covers:
- review prompt with and without a focus argument
- commit prompt with and without a ticket argument
- jtbd prompt structure
- registration smoke test (all three prompts registered)
"""

from __future__ import annotations

import pytest

knowledge_prompts = pytest.importorskip(
    "dev10x.mcp.knowledge_prompts",
    reason="mcp not installed",
)


# ── review ─────────────────────────────────────────────────────────


class TestReview:
    def test_default_target_is_current_branch(self) -> None:
        result = knowledge_prompts.review()

        assert "Review the current branch" in result
        assert "severity" in result

    def test_named_target_is_interpolated(self) -> None:
        result = knowledge_prompts.review(target="PR #42")

        assert "Review PR #42" in result

    def test_focus_line_appended_when_provided(self) -> None:
        result = knowledge_prompts.review(focus="payment retries")

        assert "Focus especially on: payment retries." in result

    def test_focus_line_omitted_when_blank(self) -> None:
        result = knowledge_prompts.review(focus="   ")

        assert "Focus especially on" not in result


# ── commit ─────────────────────────────────────────────────────────


class TestCommit:
    def test_summary_is_interpolated(self) -> None:
        result = knowledge_prompts.commit(summary="add retry logic")

        assert "add retry logic" in result
        assert "Max 72 characters" in result

    def test_ticket_drives_fixes_footer(self) -> None:
        result = knowledge_prompts.commit(summary="fix timeout", ticket="GH-9")

        assert "GH-9" in result
        assert "Fixes: GH-9" in result

    def test_no_ticket_falls_back_to_branch_extraction(self) -> None:
        result = knowledge_prompts.commit(summary="fix timeout")

        assert "Extract the ticket id from the branch name" in result
        assert "Fixes:" not in result


# ── jtbd ───────────────────────────────────────────────────────────


class TestJtbd:
    def test_returns_job_story_template(self) -> None:
        result = knowledge_prompts.jtbd(context="GH-340 MCP prompts")

        assert "GH-340 MCP prompts" in result
        assert "**When**" in result
        assert "**I want to**" in result
        assert "**so I can**" in result


# ── registration smoke test ────────────────────────────────────────


class TestPromptsRegistered:
    """Verify the prompts are registered with the server."""

    @pytest.mark.parametrize("name", ["review", "commit", "jtbd"])
    def test_prompt_is_registered(self, name: str) -> None:
        from dev10x.mcp._app import server

        prompts = server._prompt_manager.list_prompts()
        names = [p.name for p in prompts]
        assert name in names
