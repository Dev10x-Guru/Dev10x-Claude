"""Commit classification for release notes (GH-246 G2).

Extracted from ``collect_prs`` so the gitmoji/JTBD classification is
importable and unit-testable independently of the release-script glue.
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

SKIP_CATEGORIES: set[str] = {"version_bump"}
MAINTENANCE_CATEGORIES: set[str] = {"test", "docs", "config", "cleanup", "experimental"}


def classify_subject(subject: str) -> tuple[str, str]:
    for emoji, category in GITMOJI_CATEGORIES.items():
        if emoji in subject:
            return emoji, category
    return "", "unknown"


def classify_group(categories: set[str]) -> str:
    if "feature" in categories or "hotfix" in categories:
        return "feature"
    if "bugfix" in categories:
        return "bugfix"
    if "refactor" in categories:
        return "refactor"
    if categories <= MAINTENANCE_CATEGORIES:
        return "maintenance"
    return "feature"
