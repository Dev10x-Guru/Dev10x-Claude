"""Unit tests for dev10x.scope.safeguards_renderer (GH-170)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.scope.safeguards_renderer import render_safeguards


@pytest.fixture
def index_file(tmp_path: Path) -> Path:
    path = tmp_path / "INDEX.md"
    path.write_text(
        "| File Pattern | Primary Agent | Required References |\n"
        "|---|---|---|\n"
        "| `**/*.py` | reviewer-security | security scans |\n"
        "| `skills/**` | reviewer-skill | skill-gates.md |\n"
        "| `**/*.md` | reviewer-docs | docs only |\n"
    )
    return path


@pytest.fixture
def claude_md(tmp_path: Path) -> Path:
    path = tmp_path / "CLAUDE.md"
    path.write_text(
        "# Header\n"
        "\n"
        "- Never commit secrets to the repo.\n"
        "- Must validate input at boundaries.\n"
        "- Normal informational line.\n"
        "- Always wrap DB writes in transaction.atomic.\n"
    )
    return path


@pytest.fixture
def settings_file(tmp_path: Path) -> Path:
    path = tmp_path / "settings.local.json"
    path.write_text(
        json.dumps(
            {
                "permissions": {
                    "deny": [
                        "Bash(rm -rf:*)",
                        "Bash(curl http*)",
                    ]
                }
            }
        )
    )
    return path


class TestRenderSafeguards:
    def test_matches_security_rule(self, index_file: Path) -> None:
        out = render_safeguards(affected_files=["src/foo.py"], index_path=index_file)
        assert "reviewer-security" in out

    def test_skips_non_safeguard_keywords(self, index_file: Path) -> None:
        out = render_safeguards(affected_files=["docs/README.md"], index_path=index_file)
        assert "reviewer-docs" not in out

    def test_includes_skill_gates_rule(self, index_file: Path) -> None:
        out = render_safeguards(
            affected_files=["skills/git-commit/SKILL.md"],
            index_path=index_file,
        )
        assert "reviewer-skill" in out

    def test_empty_when_no_inputs(self, tmp_path: Path) -> None:
        idx = tmp_path / "INDEX.md"
        idx.write_text(
            "| File Pattern | Primary Agent | Refs |\n"
            "|---|---|---|\n"
            "| `**/*.txt` | reviewer-docs | nothing |\n"
        )
        out = render_safeguards(affected_files=["src/foo.py"], index_path=idx)
        assert "No safeguards matched" in out

    def test_includes_claude_md_never_lines(self, index_file: Path, claude_md: Path) -> None:
        out = render_safeguards(
            affected_files=["src/foo.py"],
            index_path=index_file,
            claude_md_path=claude_md,
        )
        assert "Never commit secrets" in out
        assert "Must validate input" in out

    def test_skips_normal_claude_md_lines(self, index_file: Path, claude_md: Path) -> None:
        out = render_safeguards(
            affected_files=["src/foo.py"],
            index_path=index_file,
            claude_md_path=claude_md,
        )
        assert "Normal informational line" not in out

    def test_includes_hook_deny_rules(self, index_file: Path, settings_file: Path) -> None:
        out = render_safeguards(
            affected_files=["src/foo.py"],
            index_path=index_file,
            settings_paths=[settings_file],
        )
        assert "Bash(rm -rf:*)" in out
        assert "Bash(curl http*)" in out

    def test_settings_missing_is_silent(self, index_file: Path, tmp_path: Path) -> None:
        out = render_safeguards(
            affected_files=["src/foo.py"],
            index_path=index_file,
            settings_paths=[tmp_path / "missing.json"],
        )
        assert "reviewer-security" in out

    def test_settings_malformed_is_silent(self, index_file: Path, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not valid json {")
        out = render_safeguards(
            affected_files=["src/foo.py"],
            index_path=index_file,
            settings_paths=[bad],
        )
        assert "reviewer-security" in out

    def test_index_missing_with_other_sources(self, tmp_path: Path, claude_md: Path) -> None:
        out = render_safeguards(
            affected_files=["src/foo.py"],
            index_path=tmp_path / "missing.md",
            claude_md_path=claude_md,
        )
        assert "Never commit secrets" in out

    def test_completely_empty_returns_marker(self, tmp_path: Path) -> None:
        out = render_safeguards(
            affected_files=["src/foo.py"],
            index_path=tmp_path / "missing.md",
        )
        assert out == "No safeguards matched. Manual additions only."

    def test_dedupes_repeated_deny_rules(self, index_file: Path, tmp_path: Path) -> None:
        a = tmp_path / "a.json"
        a.write_text(json.dumps({"permissions": {"deny": ["Bash(rm:*)"]}}))
        b = tmp_path / "b.json"
        b.write_text(json.dumps({"permissions": {"deny": ["Bash(rm:*)"]}}))
        out = render_safeguards(
            affected_files=["src/foo.py"],
            index_path=index_file,
            settings_paths=[a, b],
        )
        assert out.count("Bash(rm:*)") == 1
