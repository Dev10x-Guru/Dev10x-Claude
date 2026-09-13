"""Shared JTBD extraction and Slack formatting helpers (GH-246 F5)."""

from __future__ import annotations

import re

# Accepts third-person domain-actor voice (`**the dealer wants to** …,
# **so the service writer can** …`) as well as the legacy first-person
# (`**I want to** …, **so I can** …`) form for already-merged PRs (GH-847).
# The actor/beneficiary slots match any concrete role phrase; the outcome
# verb may be "can", "don't", or "doesn't".
#
# The motivation clause mirrors `pr_body`'s shape rather than listing verb
# forms. Demanding a literal `wants to**` made the extractor STRICTER than
# the validator, which has accepted the GH-1258 outcome frame
# (`**the dealer wants** the reason to be obvious`) ever since. An
# extractor stricter than its validator is the silent-omission bug in
# reverse: the PR passes and the story never reaches release notes.
JTBD_PATTERN: re.Pattern[str] = re.compile(
    r"\*\*When\*\*\s+(.+?)\s*,\s*\*\*[^*\s][^*]*\bwants?\b[^*]*\*\*\s+(.+?)\s*,"
    r"\s*\*\*so (?:.+? (?:can|don't|doesn't))\*\*\s+(.+?)(?:\.|$)",
    re.DOTALL,
)

# GH-1291: `pr_body` accepts a Job Story in the project's language, so the
# extractor has to find one too. Without this the validator would admit a
# Polish story and release-notes collection would silently omit it — a
# loud rejection traded for a quiet hole, which is worse than either.
JTBD_PATTERN_PL: re.Pattern[str] = re.compile(
    r"\*\*Gdy\*\*\s+(.+?)\s*,\s*\*\*[^*\s][^*]*\bchc[ei]\b[^*]*\*\*\s+(.+?)\s*,"
    r"\s*\*\*żeby\b[^*]*\bm(?:óg[łl]|ogł[aoy]|ogli)\b[^*]*\*\*\s+(.+?)(?:\.|$)",
    re.DOTALL,
)

JTBD_PATTERNS: tuple[re.Pattern[str], ...] = (JTBD_PATTERN, JTBD_PATTERN_PL)

# The opening marker of each accepted dialect, used to find where a story
# starts when scanning line by line.
_OPENING_MARKERS: tuple[str, ...] = ("**When**", "**Gdy**")


def extract_jtbd(body: str) -> str | None:
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(_OPENING_MARKERS):
            jtbd_lines = [line.strip()]
            for next_line in lines[i + 1 :]:
                if not next_line.strip() or next_line.startswith("#"):
                    break
                jtbd_lines.append(next_line.strip())
            return " ".join(jtbd_lines)
    return None


def extract_jtbd_structured(body: str) -> str | None:
    for pattern in JTBD_PATTERNS:
        match = pattern.search(body)
        if not match:
            continue
        full = body[match.start() : match.end()]
        full = full.replace("\n", " ").strip()
        if not full.endswith("."):
            full += "."
        return full
    return None


def md_to_slack_bold(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
