"""Unit tests for dev10x.scope.norms_renderer (GH-170)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.scope.norms_renderer import render_norms


@pytest.fixture
def index_file(tmp_path: Path) -> Path:
    path = tmp_path / "INDEX.md"
    path.write_text(
        "| File Pattern | Primary Agent | Required References |\n"
        "|---|---|---|\n"
        "| `**/*.py`, `**/*.sh` | reviewer-generic | "
        "review-checks-common.md |\n"
        "| `skills/**` | reviewer-skill | skill-naming.md |\n"
        "| `**/migrations/*.py` | reviewer-migration | (self-contained) |\n"
    )
    return path


class TestRenderNorms:
    def test_matches_python_file(self, index_file: Path) -> None:
        out = render_norms(affected_files=["src/foo/bar.py"], index_path=index_file)
        assert "reviewer-generic" in out

    def test_matches_skill_path(self, index_file: Path) -> None:
        out = render_norms(
            affected_files=["skills/git-commit/SKILL.md"],
            index_path=index_file,
        )
        assert "reviewer-skill" in out

    def test_renders_header(self, index_file: Path) -> None:
        out = render_norms(affected_files=["src/foo.py"], index_path=index_file)
        assert "Auto-populated by dev10x.scope.norms_renderer" in out

    def test_no_matches_returns_empty_body(self, index_file: Path) -> None:
        out = render_norms(affected_files=["docs/readme.txt"], index_path=index_file)
        assert "No project rules matched" in out

    def test_missing_index_returns_empty(self, tmp_path: Path) -> None:
        out = render_norms(
            affected_files=["src/foo.py"],
            index_path=tmp_path / "missing.md",
        )
        assert "No project rules matched" in out

    def test_dedupes_repeated_sources(self, tmp_path: Path) -> None:
        idx = tmp_path / "INDEX.md"
        idx.write_text(
            "| File Pattern | Primary Agent | Refs |\n"
            "|---|---|---|\n"
            "| `**/*.py` | reviewer-generic | a |\n"
            "| `**/*.sh` | reviewer-generic | a |\n"
        )
        out = render_norms(affected_files=["src/a.py", "src/b.sh"], index_path=idx)
        assert out.count("reviewer-generic") == 1

    def test_multiple_patterns_in_listing(self, index_file: Path) -> None:
        out = render_norms(affected_files=["src/foo.py"], index_path=index_file)
        assert "`**/*.py`" in out

    def test_migrations_path_matches(self, index_file: Path) -> None:
        out = render_norms(
            affected_files=[
                "src/app/migrations/0001_initial.py",
            ],
            index_path=index_file,
        )
        assert "reviewer-migration" in out
