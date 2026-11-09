from __future__ import annotations

import re

import pytest

from dev10x.core.name_boundary import NAME_START, name_pattern


class TestNamePattern:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("rg --pre=sh x", True),
            ("run `rg` here", True),
            ("git merge main", False),
            ("target", False),
            ("rg-wrapper", False),
            ("my-rg", False),
            ("sort -o out", True),
        ],
    )
    def test_matches_only_whole_hyphen_aware_words(self, text: str, expected: bool) -> None:
        pattern = name_pattern(names=("rg", "sort"))

        assert (pattern.search(text) is not None) is expected

    def test_escapes_names(self) -> None:
        pattern = name_pattern(names=("a.b",))

        assert pattern.search("axb") is None

    def test_passes_flags_through(self) -> None:
        pattern = name_pattern(names=("Reviewer",), flags=re.IGNORECASE)

        assert pattern.search("ask the REVIEWER") is not None


class TestNameStart:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("kubectl get pods", True),
            ("my-kubectl get", False),
            ("xkubectl", False),
        ],
    )
    def test_rejects_a_preceding_word_or_hyphen(self, text: str, expected: bool) -> None:
        pattern = re.compile(rf"{NAME_START}kubectl\b")

        assert (pattern.search(text) is not None) is expected
