"""Tests for the strict and tolerant YAML-mapping loads (GH-1770)."""

from __future__ import annotations

from pathlib import Path

import pytest
from dev10x.domain.documents.yaml_mapping import (
    YamlMappingError,
    load_yaml_mapping,
    read_yaml_mapping,
)


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "config.yaml"


class TestRead:
    def test_missing_file_is_empty(self, path: Path) -> None:
        assert read_yaml_mapping(path) == {}

    @pytest.mark.parametrize(
        "text", ["", "\n", "# only a comment\n"], ids=["empty", "blank", "comment"]
    )
    def test_empty_file_is_empty(self, path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")

        assert read_yaml_mapping(path) == {}

    def test_mapping(self, path: Path) -> None:
        path.write_text("a: 1\n", encoding="utf-8")

        assert read_yaml_mapping(path) == {"a": 1}

    @pytest.mark.parametrize(
        ("content", "message"),
        [
            (b"a: [unclosed\n", "not valid YAML"),
            (b"- a list\n", "must hold a mapping"),
            (b"just a string\n", "must hold a mapping"),
            (b"\xff\xfe\x00bad", "unreadable"),
        ],
        ids=["bad-yaml", "list", "scalar", "undecodable"],
    )
    def test_names_the_problem_and_the_file(
        self, path: Path, content: bytes, message: str
    ) -> None:
        path.write_bytes(content)

        with pytest.raises(YamlMappingError) as raised:
            read_yaml_mapping(path)

        assert (message in str(raised.value), str(path) in str(raised.value)) == (True, True)

    def test_a_directory_is_unreadable(self, path: Path) -> None:
        path.mkdir()

        with pytest.raises(YamlMappingError, match="unreadable"):
            read_yaml_mapping(path)


class TestLoad:
    @pytest.mark.parametrize(
        "content",
        [b"a: [unclosed\n", b"- a list\n", b"\xff\xfe\x00bad", b""],
        ids=["bad-yaml", "list", "undecodable", "empty"],
    )
    def test_degrades_to_empty(self, path: Path, content: bytes) -> None:
        path.write_bytes(content)

        assert load_yaml_mapping(path) == {}

    def test_missing_file_is_empty(self, path: Path) -> None:
        assert load_yaml_mapping(path) == {}

    def test_directory_is_empty(self, path: Path) -> None:
        path.mkdir()

        assert load_yaml_mapping(path) == {}

    def test_mapping(self, path: Path) -> None:
        path.write_text("a: 1\n", encoding="utf-8")

        assert load_yaml_mapping(path) == {"a": 1}
