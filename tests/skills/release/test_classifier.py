"""Tests for the release commit classifier (GH-246 G2)."""

from __future__ import annotations

import pytest

from dev10x.skills.release.classifier import (
    GITMOJI_CATEGORIES,
    classify_group,
    classify_subject,
)


class TestClassifySubject:
    @pytest.mark.parametrize(
        ("subject", "expected"),
        [
            ("✨ GH-1 Add feature", ("✨", "feature")),
            ("🐛 GH-2 Fix bug", ("🐛", "bugfix")),
            ("♻️ GH-3 Refactor", ("♻️", "refactor")),
            ("🔖 Bump version", ("🔖", "version_bump")),
            ("🚑 Hotfix prod", ("🚑", "hotfix")),
        ],
    )
    def test_maps_known_gitmoji(self, subject: str, expected: tuple[str, str]):
        assert classify_subject(subject=subject) == expected

    def test_unknown_subject_returns_unknown(self):
        assert classify_subject(subject="plain commit, no gitmoji") == ("", "unknown")

    def test_first_matching_gitmoji_wins(self):
        first_emoji = next(iter(GITMOJI_CATEGORIES))
        subject = f"{first_emoji} GH-9 leading gitmoji"
        assert classify_subject(subject=subject)[0] == first_emoji


class TestClassifyGroup:
    @pytest.mark.parametrize(
        ("categories", "expected"),
        [
            ({"feature", "docs"}, "feature"),
            ({"hotfix"}, "feature"),
            ({"bugfix", "test"}, "bugfix"),
            ({"refactor", "config"}, "refactor"),
            ({"test", "docs", "config"}, "maintenance"),
            (set(), "maintenance"),
            ({"unknown"}, "feature"),
        ],
    )
    def test_group_precedence(self, categories: set[str], expected: str):
        assert classify_group(categories=categories) == expected
