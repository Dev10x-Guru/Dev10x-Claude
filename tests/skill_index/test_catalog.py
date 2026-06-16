"""Tests for the SkillCatalog aggregate (audit finding D7)."""

from __future__ import annotations

from pathlib import Path

from dev10x.skill_index.builder import SkillEntry
from dev10x.skill_index.catalog import SkillCatalog


def _skill_md(*, name: str, invocation: str | None = None) -> str:
    lines = ["---", f"name: {name}"]
    if invocation is not None:
        lines.append(f"invocation-name: {invocation}")
    lines += ["description: x", "---", "", "Overview"]
    return "\n".join(lines)


def _make_skill(root: Path, dirname: str, text: str) -> None:
    skill_dir = root / dirname
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(text, encoding="utf-8")


class TestFromDirs:
    def test_scans_and_sorts_entries(self, tmp_path: Path) -> None:
        _make_skill(tmp_path, "zebra", _skill_md(name="Dev10x:zebra"))
        _make_skill(tmp_path, "alpha", _skill_md(name="Dev10x:alpha"))

        catalog = SkillCatalog.from_dirs(skill_dirs=[tmp_path])

        assert [entry.key for entry in catalog.list()] == ["Dev10x:alpha", "Dev10x:zebra"]

    def test_empty_when_no_skills(self, tmp_path: Path) -> None:
        assert SkillCatalog.from_dirs(skill_dirs=[tmp_path]).list() == []


class TestList:
    def test_returns_a_copy_not_the_internal_tuple(self) -> None:
        entry = SkillEntry(key="Dev10x:x", name="Dev10x:x")
        catalog = SkillCatalog(entries=(entry,))

        listed = catalog.list()
        listed.append(SkillEntry(key="Dev10x:y", name="Dev10x:y"))

        assert catalog.list() == [entry]


class TestLookup:
    def test_finds_by_key(self) -> None:
        entry = SkillEntry(key="Dev10x:public", name="internal-name")
        catalog = SkillCatalog(entries=(entry,))

        assert catalog.lookup(name="Dev10x:public") == entry

    def test_falls_back_to_name_when_no_key_match(self) -> None:
        entry = SkillEntry(key="Dev10x:public", name="internal-name")
        catalog = SkillCatalog(entries=(entry,))

        assert catalog.lookup(name="internal-name") == entry

    def test_key_match_wins_over_name_match(self) -> None:
        by_key = SkillEntry(key="shared", name="other")
        by_name = SkillEntry(key="Dev10x:other", name="shared")
        catalog = SkillCatalog(entries=(by_key, by_name))

        assert catalog.lookup(name="shared") == by_key

    def test_unknown_name_returns_none(self) -> None:
        catalog = SkillCatalog(entries=(SkillEntry(key="Dev10x:x", name="Dev10x:x"),))

        assert catalog.lookup(name="Dev10x:missing") is None

    def test_blank_name_returns_none(self) -> None:
        catalog = SkillCatalog(entries=(SkillEntry(key="Dev10x:x", name="Dev10x:x"),))

        assert catalog.lookup(name="   ") is None
