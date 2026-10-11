"""Slack MCP tool registrations (split from misc_tools.py, GH-1548)."""

from __future__ import annotations

from dev10x.domain.common.result import to_wire
from dev10x.mcp._app import server


@server.tool()
async def slack_thread_is_forward(
    parent_body: str,
    reply_count: int,
) -> dict:
    """Detect whether a Slack thread is likely a forward / cross-post (GH-218).

    Pure heuristic over an already-fetched thread payload. The caller
    fetches the thread via `mcp__claude_ai_Slack__slack_read_thread`
    and passes the parent message body + reply count here.

    Signals:
    - short_body: parent body word count below threshold (~30 words)
    - zero_replies: thread has no replies
    - external_link OR forwarding_language: parent references an
      external URL or uses forwarding phrasing (fwd, FYI, sharing, ...)

    Confidence:
    - high: all 3 signals present
    - medium: exactly 2 signals present
    - low: 0 or 1 signals present

    Args:
        parent_body: The parent message text from the Slack thread.
        reply_count: Number of replies on the thread.

    Returns:
        Dictionary with keys: is_forward (bool), confidence (str),
        signals (list[str]), upstream_hints (list[str]).
    """
    from dev10x.core.utilities import slack as slack_helper

    return to_wire(
        await slack_helper.slack_thread_is_forward(
            parent_body=parent_body,
            reply_count=reply_count,
        )
    )
