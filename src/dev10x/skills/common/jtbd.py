"""Shared JTBD extraction and Slack formatting helpers (GH-246 F5)."""

from __future__ import annotations

import re

JTBD_PATTERN: re.Pattern[str] = re.compile(
    r"\*\*When\*\*\s+(.+?)\s*,\s*\*\*(?:I want to|they want to)\*\*\s+(.+?)\s*,"
    r"\s*\*\*so (?:I can|they can|I don't)\*\*\s+(.+?)(?:\.|$)",
    re.DOTALL,
)


def extract_jtbd(body: str) -> str | None:
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith("**When**"):
            jtbd_lines = [line.strip()]
            for next_line in lines[i + 1 :]:
                if not next_line.strip() or next_line.startswith("#"):
                    break
                jtbd_lines.append(next_line.strip())
            return " ".join(jtbd_lines)
    return None


def extract_jtbd_structured(body: str) -> str | None:
    match = JTBD_PATTERN.search(body)
    if match:
        full = body[match.start() : match.end()]
        full = full.replace("\n", " ").strip()
        if not full.endswith("."):
            full += "."
        return full
    return None


def md_to_slack_bold(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
