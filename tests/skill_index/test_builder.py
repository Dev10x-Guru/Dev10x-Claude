"""Tests for the skill-index builder logic (GH-248 G11)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.skill_index.builder import (
    SkillEntry,
    extract_front_matter,
    parse_skill_frontmatter,
    scan_skill_dirs,
)


def _skill_md(
    *, name: str | None = None, invocation: str | None = None, body: str = "Overview"
) -> str:
    lines = ["---"]
    if name is not None:
        lines.append(f"name: {name}")
    if invocation is not None:
        lines.append(f"invocation-name: {invocation}")
    lines += ["description: x", "---", "", body]
    return "\n".join(lines)


class TestParseSkillFrontmatter:
    def test_invocation_name_is_preferred_key(self):
        text = _skill_md(name="Dev10x:git-commit", invocation="Dev10x:git-commit")
        entry = parse_skill_frontmatter(text=text)
        assert entry == SkillEntry(key="Dev10x:git-commit", name="Dev10x:git-commit")

    def test_falls_back_to_name_when_no_invocation_name(self):
        text = _skill_md(name="Dev10x:park")
        entry = parse_skill_frontmatter(text=text)
        assert entry is not None
        assert entry.key == "Dev10x:park"
        assert entry.name == "Dev10x:park"

    def test_invocation_name_overrides_differing_name(self):
        text = _skill_md(name="internal-name", invocation="Dev10x:public")
        entry = parse_skill_frontmatter(text=text)
        assert entry is not None
        assert entry.key == "Dev10x:public"
        assert entry.name == "internal-name"

    @pytest.mark.parametrize(
        "text",
        [
            "no front matter here\njust prose",
            "---\nname: Dev10x:x\ndescription: unterminated front matter",
            "---\n: : : not valid yaml :\n  - broken\n---\nbody",
            "---\n- just\n- a\n- list\n---\nbody",
        ],
    )
    def test_malformed_or_missing_front_matter_returns_none(self, text: str):
        assert parse_skill_frontmatter(text=text) is None

    @pytest.mark.parametrize(
        "name",
        ["my-skill-name", "{{cookiecutter.name}}", ""],
    )
    def test_placeholder_and_empty_names_rejected(self, name: str):
        assert parse_skill_frontmatter(text=_skill_md(name=name)) is None

    def test_missing_name_key_returns_none(self):
        text = "---\ndescription: only a description\n---\nbody"
        assert parse_skill_frontmatter(text=text) is None

    def test_trailing_comment_stripped_from_key(self):
        text = _skill_md(name="Dev10x:thing", invocation="Dev10x:thing # legacy")
        entry = parse_skill_frontmatter(text=text)
        assert entry is not None
        assert entry.key == "Dev10x:thing"

    def test_invocation_name_that_reduces_to_empty_key_returns_none(self):
        text = '---\nname: Dev10x:x\ninvocation-name: "#only-a-comment"\n---\nbody'
        assert parse_skill_frontmatter(text=text) is None

    def test_source_path_is_preserved(self):
        path = Path("/skills/x/SKILL.md")
        entry = parse_skill_frontmatter(text=_skill_md(name="Dev10x:x"), source=path)
        assert entry is not None
        assert entry.source == path


class TestExtractFrontMatter:
    def test_returns_mapping(self):
        assert extract_front_matter(text=_skill_md(name="Dev10x:x")) == {
            "name": "Dev10x:x",
            "description": "x",
        }

    def test_no_opening_fence_returns_none(self):
        assert extract_front_matter(text="plain text") is None


class TestScanSkillDirs:
    def _make_skill(self, root: Path, dirname: str, text: str) -> None:
        skill_dir = root / dirname
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(text, encoding="utf-8")

    def test_returns_entries_sorted_by_key(self, tmp_path: Path):
        self._make_skill(tmp_path, "zebra", _skill_md(name="Dev10x:zebra"))
        self._make_skill(tmp_path, "alpha", _skill_md(name="Dev10x:alpha"))
        self._make_skill(tmp_path, "mid", _skill_md(name="Dev10x:mid"))

        entries = scan_skill_dirs(skill_dirs=[tmp_path])
        assert [entry.key for entry in entries] == [
            "Dev10x:alpha",
            "Dev10x:mid",
            "Dev10x:zebra",
        ]

    def test_directory_without_skill_md_is_skipped(self, tmp_path: Path):
        (tmp_path / "empty").mkdir()
        self._make_skill(tmp_path, "real", _skill_md(name="Dev10x:real"))

        entries = scan_skill_dirs(skill_dirs=[tmp_path])
        assert [entry.key for entry in entries] == ["Dev10x:real"]

    def test_placeholder_skill_excluded_from_scan(self, tmp_path: Path):
        self._make_skill(tmp_path, "good", _skill_md(name="Dev10x:good"))
        self._make_skill(tmp_path, "tmpl", _skill_md(name="my-skill-name"))

        entries = scan_skill_dirs(skill_dirs=[tmp_path])
        assert [entry.key for entry in entries] == ["Dev10x:good"]

    def test_multiple_dirs_merged_and_sorted(self, tmp_path: Path):
        local = tmp_path / "local"
        plugin = tmp_path / "plugin"
        local.mkdir()
        plugin.mkdir()
        self._make_skill(local, "b", _skill_md(name="Dev10x:b"))
        self._make_skill(plugin, "a", _skill_md(name="Dev10x:a"))

        entries = scan_skill_dirs(skill_dirs=[local, plugin])
        assert [entry.key for entry in entries] == ["Dev10x:a", "Dev10x:b"]
