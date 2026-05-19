"""Unit tests for dev10x.scope.index_parser (GH-170)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.scope.index_parser import RuleEntry, parse_index


@pytest.fixture
def index_file(tmp_path: Path) -> Path:
    content = """# Routing

Intro text.

## File Patterns -> Agents -> References

| File Pattern | Primary Agent | Required References |
|---|---|---|
| `**/*.py`, `**/*.sh` | reviewer-generic | review-checks-common.md |
| `skills/**` | reviewer-skill | skill-naming.md |
| `**/migrations/*.py` | reviewer-migration | (self-contained) |

Trailing prose.
"""
    path = tmp_path / "INDEX.md"
    path.write_text(content)
    return path


class TestParseIndex:
    def test_returns_rule_entries(self, index_file: Path) -> None:
        entries = parse_index(index_path=index_file)
        assert len(entries) == 3
        assert all(isinstance(e, RuleEntry) for e in entries)

    def test_first_entry_patterns(self, index_file: Path) -> None:
        entries = parse_index(index_path=index_file)
        assert entries[0].patterns == ("**/*.py", "**/*.sh")

    def test_source_extracted(self, index_file: Path) -> None:
        entries = parse_index(index_path=index_file)
        assert entries[0].source == "reviewer-generic"

    def test_description_extracted(self, index_file: Path) -> None:
        entries = parse_index(index_path=index_file)
        assert entries[0].description == "review-checks-common.md"

    def test_skills_pattern(self, index_file: Path) -> None:
        entries = parse_index(index_path=index_file)
        assert entries[1].patterns == ("skills/**",)
        assert entries[1].source == "reviewer-skill"

    def test_raises_on_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            parse_index(index_path=tmp_path / "missing.md")

    def test_empty_when_no_table(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.md"
        path.write_text("# Title\n\nNo tables here.\n")
        assert parse_index(index_path=path) == []

    def test_skips_rows_without_patterns(self, tmp_path: Path) -> None:
        path = tmp_path / "no-patterns.md"
        path.write_text(
            "| File Pattern | Primary Agent | Refs |\n"
            "|---|---|---|\n"
            "| no backticks here | x | y |\n"
            "| `**/*.py` | good | ok |\n"
        )
        entries = parse_index(index_path=path)
        assert len(entries) == 1
        assert entries[0].source == "good"
