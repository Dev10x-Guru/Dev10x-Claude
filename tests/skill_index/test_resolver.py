"""Tests for the canonical skill-path resolver (GH-611)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.skill_index.builder import SkillEntry
from dev10x.skill_index.catalog import SkillCatalog
from dev10x.skill_index.resolver import (
    ResolvedSkill,
    SkillPathResolver,
    SkillResolution,
    feature_name,
)


def _entry(*, key: str, name: str | None = None, directory: str | None = None) -> SkillEntry:
    source = Path(directory) / "SKILL.md" if directory is not None else None
    return SkillEntry(key=key, name=name or key, source=source)


def _resolver(*entries: SkillEntry) -> SkillPathResolver:
    return SkillPathResolver(catalog=SkillCatalog(entries=entries))


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


class TestFeatureName:
    @pytest.mark.parametrize(
        ("invocation", "expected"),
        [
            ("Dev10x:git-commit", "git-commit"),
            ("my:daily-yt", "daily-yt"),
            ("park", "park"),
            ("  Dev10x:scope  ", "scope"),
        ],
    )
    def test_strips_namespace_prefix(self, invocation: str, expected: str) -> None:
        assert feature_name(invocation_name=invocation) == expected


class TestResolveByKey:
    def test_resolves_plugin_skill_to_real_directory(self) -> None:
        resolver = _resolver(
            _entry(key="Dev10x:git-commit", directory="/plugin/skills/git-commit")
        )

        resolution = resolver.resolve(name="Dev10x:git-commit")

        assert resolution.is_resolved
        assert resolution.directory == Path("/plugin/skills/git-commit")

    def test_resolves_personal_skill_with_colon_dir(self) -> None:
        resolver = _resolver(
            _entry(key="my:daily-yt", directory="/home/u/.claude/skills/my:daily-yt")
        )

        resolution = resolver.resolve(name="my:daily-yt")

        assert resolution.is_resolved
        assert resolution.directory == Path("/home/u/.claude/skills/my:daily-yt")

    def test_key_match_without_source_is_missing(self) -> None:
        resolver = _resolver(_entry(key="Dev10x:ghost"))

        resolution = resolver.resolve(name="Dev10x:ghost")

        assert resolution.is_missing
        assert resolution.directory is None


class TestResolveByName:
    def test_falls_back_to_internal_name(self) -> None:
        resolver = _resolver(
            _entry(key="Dev10x:public", name="internal-name", directory="/p/skills/public")
        )

        resolution = resolver.resolve(name="internal-name")

        assert resolution.is_resolved
        assert resolution.directory == Path("/p/skills/public")


class TestResolveByFeature:
    def test_bare_feature_resolves_single_match(self) -> None:
        resolver = _resolver(_entry(key="Dev10x:scope", directory="/p/skills/scope"))

        resolution = resolver.resolve(name="scope")

        assert resolution.is_resolved
        assert resolution.directory == Path("/p/skills/scope")

    def test_duplicate_feature_across_plugins_is_ambiguous(self) -> None:
        resolver = _resolver(
            _entry(key="A:commit", directory="/a/skills/commit"),
            _entry(key="B:commit", directory="/b/skills/commit"),
        )

        resolution = resolver.resolve(name="commit")

        assert resolution.is_ambiguous
        assert {c.directory for c in resolution.candidates} == {
            Path("/a/skills/commit"),
            Path("/b/skills/commit"),
        }

    def test_prefix_disambiguates_duplicate_feature(self) -> None:
        resolver = _resolver(
            _entry(key="A:commit", directory="/a/skills/commit"),
            _entry(key="B:commit", directory="/b/skills/commit"),
        )

        resolution = resolver.resolve(name="A:commit")

        assert resolution.is_resolved
        assert resolution.directory == Path("/a/skills/commit")


class TestDuplicateKey:
    def test_same_key_two_locations_is_ambiguous(self) -> None:
        resolver = _resolver(
            _entry(key="dup", directory="/a/skills/dup"),
            _entry(key="dup", directory="/b/skills/dup"),
        )

        resolution = resolver.resolve(name="dup")

        assert resolution.is_ambiguous
        assert len(resolution.candidates) == 2


class TestDedupe:
    def test_same_directory_scanned_twice_resolves_once(self) -> None:
        resolver = _resolver(
            _entry(key="dup", directory="/a/skills/dup"),
            _entry(key="dup", directory="/a/skills/dup"),
        )

        resolution = resolver.resolve(name="dup")

        assert resolution.is_resolved
        assert resolution.directory == Path("/a/skills/dup")


class TestMissing:
    def test_unknown_name_is_missing(self) -> None:
        resolver = _resolver(_entry(key="Dev10x:x", directory="/p/skills/x"))

        resolution = resolver.resolve(name="Dev10x:nope")

        assert resolution.is_missing

    def test_blank_name_is_missing(self) -> None:
        resolver = _resolver(_entry(key="Dev10x:x", directory="/p/skills/x"))

        resolution = resolver.resolve(name="   ")

        assert resolution.is_missing


class TestResolvedSkill:
    def test_skill_file_is_under_directory(self) -> None:
        resolved = ResolvedSkill(
            entry=_entry(key="Dev10x:x", directory="/p/skills/x"),
            directory=Path("/p/skills/x"),
        )

        assert resolved.skill_file == Path("/p/skills/x/SKILL.md")


class TestResolutionFlags:
    def test_resolved_excludes_other_states(self) -> None:
        resolved = ResolvedSkill(entry=_entry(key="x", directory="/p/x"), directory=Path("/p/x"))
        resolution = SkillResolution(query="x", resolved=resolved)

        assert resolution.is_resolved
        assert not resolution.is_ambiguous
        assert not resolution.is_missing

    def test_empty_resolution_is_missing(self) -> None:
        resolution = SkillResolution(query="x")

        assert resolution.is_missing
        assert not resolution.is_resolved
        assert not resolution.is_ambiguous
        assert resolution.directory is None


class TestFromDirs:
    def test_scans_real_skill_dirs_and_resolves(self, tmp_path: Path) -> None:
        _make_skill(tmp_path, "git-commit", _skill_md(name="Dev10x:git-commit"))

        resolver = SkillPathResolver.from_dirs(skill_dirs=[tmp_path])
        resolution = resolver.resolve(name="Dev10x:git-commit")

        assert resolution.is_resolved
        assert resolution.directory == tmp_path / "git-commit"
        assert resolution.resolved is not None
        assert resolution.resolved.skill_file == tmp_path / "git-commit" / "SKILL.md"

    def test_default_catalog_is_empty(self) -> None:
        resolver = SkillPathResolver()

        assert resolver.resolve(name="Dev10x:anything").is_missing
