"""Shared JTBD extraction and Slack formatting helpers (GH-246 F5)."""

from __future__ import annotations

import re
from collections.abc import Iterator

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

# GH-1293: how much of a body the structured patterns are allowed to see.
#
# Their cost is (failing `**When**` positions) x (lazy expansion at each),
# so it grows with the BODY, not with the story — measured at ~8x per
# doubling: 107ms at 4.6KB, 6.8s at 18.4KB, minutes at GitHub's 65536-char
# ceiling. Release-notes collection runs this over every merged PR body,
# and on a repo taking outside contributions those bodies are written by
# strangers.
#
# Windowing is preferred over bounding the patterns' own free groups
# (`[^*]+?` instead of `.+?`). That alternative looks tidier and is the
# one the issue first proposed, but a clause containing bold text would
# stop matching — turning a loud nothing-to-extract into a story silently
# missing from release notes, which is exactly the defect GH-1291 closed.
# A window changes no pattern, so every story that still matches, matches
# as it did. Each window starts at an opening marker rather than at a
# fixed offset, so a story is never cut in half by where it happens to
# sit — only by its own length, and 2000 characters is several times what
# a one-sentence story needs.
_SEARCH_WINDOW_CHARS = 2000

# One window is not enough: the FIRST opening marker in a body need not
# belong to the real story — a quoted example or a malformed attempt can
# come first — and parking on it would drop the story below, which is the
# silent omission this fix exists to avoid. So successive windows are
# tried. The count is bounded because each one costs, and a body whose
# twelfth window still has not yielded a story is not carrying one where
# release notes would look.
_MAX_STORY_WINDOWS = 12

# Consecutive windows overlap by this much so a marker sitting near a
# window's end still has room for the rest of its story inside that same
# window. Without the overlap a story could be cut by a boundary it
# merely happened to land on — the same positional accident the
# marker-anchored window exists to avoid. It doubles as the longest
# story this extractor promises to find.
_STORY_OVERLAP_CHARS = 1000


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


def _story_windows(body: str) -> Iterator[str]:
    """The slices the structured patterns are allowed to search.

    Each window is located by a plain substring scan for an opening
    marker — linear, and unable to backtrack — so the expensive patterns
    only ever see a bounded slice, however large the body is.
    """
    position = 0
    for _ in range(_MAX_STORY_WINDOWS):
        starts = [
            found
            for found in (body.find(marker, position) for marker in _OPENING_MARKERS)
            if found >= 0
        ]
        if not starts:
            return
        start = min(starts)
        yield body[start : start + _SEARCH_WINDOW_CHARS]
        position = start + _SEARCH_WINDOW_CHARS - _STORY_OVERLAP_CHARS


def extract_jtbd_structured(body: str) -> str | None:
    for window in _story_windows(body):
        for pattern in JTBD_PATTERNS:
            match = pattern.search(window)
            if not match:
                continue
            full = window[match.start() : match.end()]
            full = full.replace("\n", " ").strip()
            if not full.endswith("."):
                full += "."
            return full
    return None


def md_to_slack_bold(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
