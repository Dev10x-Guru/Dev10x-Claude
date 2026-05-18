from __future__ import annotations

import pytest

from dev10x.domain.common.result import SuccessResult
from dev10x.github import slack


class TestSlackThreadIsForward:
    @pytest.mark.asyncio
    async def test_all_three_signals_returns_high_confidence(self) -> None:
        result = await slack.slack_thread_is_forward(
            parent_body="FYI flagging this: https://linear.app/team/issue/X-1",
            reply_count=0,
        )

        assert isinstance(result, SuccessResult)
        assert result.value["is_forward"] is True
        assert result.value["confidence"] == "high"
        assert "short_body" in result.value["signals"]
        assert "zero_replies" in result.value["signals"]
        # external_link wins over forwarding_language when both present
        assert "external_link" in result.value["signals"]
        assert "https://linear.app/team/issue/X-1" in result.value["upstream_hints"]

    @pytest.mark.asyncio
    async def test_two_signals_returns_medium_confidence(self) -> None:
        result = await slack.slack_thread_is_forward(
            parent_body="Short note here",
            reply_count=0,
        )

        assert result.value["is_forward"] is True
        assert result.value["confidence"] == "medium"
        assert set(result.value["signals"]) == {"short_body", "zero_replies"}
        assert result.value["upstream_hints"] == []

    @pytest.mark.asyncio
    async def test_one_signal_returns_low_confidence(self) -> None:
        long_body = "word " * 50 + "and a final period."
        result = await slack.slack_thread_is_forward(
            parent_body=long_body,
            reply_count=0,
        )

        assert result.value["is_forward"] is False
        assert result.value["confidence"] == "low"
        assert result.value["signals"] == ["zero_replies"]

    @pytest.mark.asyncio
    async def test_no_signals_returns_low_confidence(self) -> None:
        long_body = "word " * 50
        result = await slack.slack_thread_is_forward(
            parent_body=long_body,
            reply_count=5,
        )

        assert result.value["is_forward"] is False
        assert result.value["confidence"] == "low"
        assert result.value["signals"] == []

    @pytest.mark.asyncio
    async def test_forwarding_language_without_external_link(self) -> None:
        result = await slack.slack_thread_is_forward(
            parent_body="fwd from #another-channel for visibility",
            reply_count=0,
        )

        assert result.value["confidence"] == "high"
        assert "forwarding_language" in result.value["signals"]
        assert "external_link" not in result.value["signals"]

    @pytest.mark.asyncio
    async def test_slack_internal_url_is_not_external(self) -> None:
        body = "see https://workspace.slack.com/archives/C123/p456 for context"
        result = await slack.slack_thread_is_forward(
            parent_body=body,
            reply_count=0,
        )

        # short_body + zero_replies = medium; Slack URL must not count
        # as external_link
        assert "external_link" not in result.value["signals"]
        assert result.value["confidence"] == "medium"

    @pytest.mark.asyncio
    async def test_extracts_only_external_urls(self) -> None:
        body = "fwd: see https://example.com/x and https://workspace.slack.com/archives/C1/p2"
        result = await slack.slack_thread_is_forward(
            parent_body=body,
            reply_count=0,
        )

        assert result.value["upstream_hints"] == ["https://example.com/x"]
