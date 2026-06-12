from __future__ import annotations

import re

import pytest

from dev10x.domain.common.mktmp_path import (
    MKTMP_GENERALIZE_PATTERN,
    MKTMP_PATH_PATTERN,
    MktmpPath,
)


class TestIsMktmpPath:
    @pytest.mark.parametrize(
        "value",
        [
            "/tmp/Dev10x/git/commit-msg.hVgpBkyGhKAp.txt",
            "Write(/tmp/Dev10x/sess/file.abc123def.json)",
            "/tmp/Dev10x/s/f.abcdef",  # no extension still matches the core shape
        ],
    )
    def test_detects_mktmp_paths(self, value: str) -> None:
        assert MktmpPath.is_mktmp_path(value) is True

    @pytest.mark.parametrize(
        "value",
        ["/tmp/other/file.txt", "/home/user/notes.md", "just text"],
    )
    def test_rejects_non_mktmp_paths(self, value: str) -> None:
        assert MktmpPath.is_mktmp_path(value) is False

    def test_require_extension_anchors_to_end(self) -> None:
        assert MktmpPath.is_mktmp_path(
            "/tmp/Dev10x/git/commit-msg.hVgpBkyGhKAp.txt", require_extension=True
        )

    def test_require_extension_rejects_without_trailing_extension(self) -> None:
        assert (
            MktmpPath.is_mktmp_path("/tmp/Dev10x/git/file.abcdef", require_extension=True) is False
        )


class TestGeneralizePattern:
    @pytest.mark.parametrize("replacement,expected", [(r"\1*", "*"), (r"\1**", "**")])
    def test_collapses_random_filename_to_glob(self, replacement: str, expected: str) -> None:
        entry = "Read(/tmp/Dev10x/sess/commit-msg.hVgpBkyGhKAp.txt)"
        result = re.sub(MKTMP_GENERALIZE_PATTERN, replacement, entry)

        assert result == f"Read(/tmp/Dev10x/sess/{expected})"

    def test_captures_session_directory_as_group_one(self) -> None:
        match = re.search(MKTMP_GENERALIZE_PATTERN, "/tmp/Dev10x/sess/f.abc123.md")

        assert match is not None
        assert match.group(1) == "/tmp/Dev10x/sess/"


def test_patterns_exposed_as_strings() -> None:
    assert MKTMP_PATH_PATTERN == r"/tmp/Dev10x/[^/]+/[^/]+\.[A-Za-z0-9]{6,}"
    assert MKTMP_GENERALIZE_PATTERN.startswith(r"(/tmp/Dev10x/[^/]+/)")
