"""Gitmoji registry — single source for commit-emoji knowledge (C6).

``GITMOJI_CATEGORIES`` (release-note classification) and
``BYPASS_GITMOJI`` (commit-JTBD validation bypass) previously lived in
two unrelated modules — ``skills/release/classifier`` and
``validators/commit_jtbd``. Co-locating them here gives the project one
authoritative gitmoji table so the two consumers cannot drift apart.
"""

from __future__ import annotations

GITMOJI_CATEGORIES: dict[str, str] = {
    "✨": "feature",
    "🐛": "bugfix",
    "♻️": "refactor",
    "🚚": "refactor",
    "✅": "test",
    "📝": "docs",
    "🔧": "config",
    "🩹": "fix",
    "🔥": "cleanup",
    "⚡": "perf",
    "🔒": "security",
    "💄": "ui",
    "🔖": "version_bump",
    "⚗️": "experimental",
    "🧪": "test",
    "🚑": "hotfix",
}

# Gitmoji whose commits skip the JTBD outcome-phrasing check: version
# bumps, docs, and merge commits carry no user-facing "enables X" story.
BYPASS_GITMOJI: frozenset[str] = frozenset({"🔖", "📝", "🔀"})
