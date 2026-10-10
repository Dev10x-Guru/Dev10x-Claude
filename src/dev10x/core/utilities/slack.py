"""Slack thread forward-detection helper (GH-218).

Pure, stateless heuristic over an already-fetched Slack thread payload.
The MCP tool does not call Slack itself — the caller fetches the thread
via `mcp__claude_ai_Slack__slack_read_thread` and passes the relevant
fields here. This keeps the helper testable and free of MCP-fetch
coupling.

Signals:
- Short body: parent message body word-count below threshold
- Zero replies: thread has no replies
- External artifact: parent body contains a non-Slack URL OR
  forwarding language

Confidence:
- high: all 3 signals present
- medium: exactly 2 signals present
- low: 0 or 1 signals present
"""

from __future__ import annotations

import re
from typing import Any

from dev10x.domain.common.result import Result, ok

SHORT_BODY_WORD_THRESHOLD = 30

_FORWARD_LANGUAGE_PATTERN = re.compile(
    r"\b(fwd|forwarded|forwarding|flagging|sharing|fyi|cross[- ]post(?:ing|ed)?)\b",
    re.IGNORECASE,
)

_URL_PATTERN = re.compile(r"https?://[^\s>)]+", re.IGNORECASE)

_SLACK_HOST_PATTERN = re.compile(r"^https?://[^/]*\.slack\.com(/|$)", re.IGNORECASE)


def _word_count(text: str) -> int:
    return len(text.split())


def _extract_url_hints(body: str) -> list[str]:
    return [url for url in _URL_PATTERN.findall(body) if not _SLACK_HOST_PATTERN.match(url)]


def _has_external_link(body: str) -> bool:
    return bool(_extract_url_hints(body))


def _has_forwarding_language(body: str) -> bool:
    return bool(_FORWARD_LANGUAGE_PATTERN.search(body))


async def slack_thread_is_forward(
    *,
    parent_body: str,
    reply_count: int,
) -> Result[dict[str, Any]]:
    """Detect whether a Slack thread is likely a forward / cross-post (GH-218).

    Args:
        parent_body: The parent message text from the Slack thread.
        reply_count: Number of replies on the thread (0 means none).

    Returns:
        On success: ``{"is_forward": bool, "confidence": str,
        "signals": list[str], "upstream_hints": list[str]}``.
        The function never errors — heuristic over inputs only.
    """
    signals: list[str] = []

    if _word_count(parent_body) < SHORT_BODY_WORD_THRESHOLD:
        signals.append("short_body")

    if reply_count == 0:
        signals.append("zero_replies")

    has_link = _has_external_link(parent_body)
    has_fwd_lang = _has_forwarding_language(parent_body)
    if has_link or has_fwd_lang:
        signals.append("external_link" if has_link else "forwarding_language")

    score = len(signals)
    if score >= 3:
        confidence = "high"
    elif score == 2:
        confidence = "medium"
    else:
        confidence = "low"

    return ok(
        {
            "is_forward": confidence in ("high", "medium"),
            "confidence": confidence,
            "signals": signals,
            "upstream_hints": _extract_url_hints(parent_body),
        }
    )
