"""Tests for local-skill enumeration and pre-approval (GH-116)."""

from __future__ import annotations

from pathlib import Path

import pytest

mod = pytest.importorskip(
    "dev10x.skills.permission.local_skill_approval",
    reason="dev10x not installed",
)


def _write_skill(*, root: Path, dir_name: str, name: str) -> Path:
    skill_dir = root / dir_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\n---\n\nbody\n",
    )
    return skill_dir


class TestEnumerateLocalSkills:
    def test_missing_root_returns_empty(self, tmp_path: Path) -> None:
        result = mod.enumerate_local_skills(skills_root=tmp_path / "missing")
        assert result == []

    def test_parses_name_field_from_skill_md(self, tmp_path: Path) -> None:
        _write_skill(root=tmp_path, dir_name="tt:db", name="tt:db")
        _write_skill(root=tmp_path, dir_name="tt:docker-test-env", name="tt:docker-test-env")
        _write_skill(root=tmp_path, dir_name="standalone", name="standalone")

        skills = mod.enumerate_local_skills(skills_root=tmp_path)

        assert {s.name for s in skills} == {
            "tt:db",
            "tt:docker-test-env",
            "standalone",
        }

    def test_splits_namespace_prefix(self, tmp_path: Path) -> None:
        _write_skill(root=tmp_path, dir_name="tt:db", name="tt:db")
        _write_skill(root=tmp_path, dir_name="plain", name="plain")

        skills = mod.enumerate_local_skills(skills_root=tmp_path)
        by_name = {s.name: s for s in skills}

        assert by_name["tt:db"].namespace == "tt"
        assert by_name["plain"].namespace is None


class TestEnumerateProjects:
    def test_missing_root_returns_empty(self, tmp_path: Path) -> None:
        result = mod.enumerate_projects(projects_root=tmp_path / "missing")
        assert result == []

    def test_lists_project_subdirectories(self, tmp_path: Path) -> None:
        (tmp_path / "proj-a").mkdir()
        (tmp_path / "proj-b").mkdir()
        (tmp_path / "loose-file.txt").write_text("x")

        result = mod.enumerate_projects(projects_root=tmp_path)

        assert {p.name for p in result} == {"proj-a", "proj-b"}


class TestGroupByNamespace:
    def test_clusters_by_prefix(self) -> None:
        skills = [
            mod.LocalSkill(name="tt:db", directory=Path("/x"), namespace="tt"),
            mod.LocalSkill(name="tt:git", directory=Path("/x"), namespace="tt"),
            mod.LocalSkill(name="tt:jira", directory=Path("/x"), namespace="tt"),
            mod.LocalSkill(name="my:daily", directory=Path("/x"), namespace="my"),
        ]

        groups = mod.group_by_namespace(skills=skills)

        assert len(groups) == 2
        tt = next(g for g in groups if g.namespace == "tt")
        assert len(tt.skills) == 3
        assert tt.threshold_met is True
        assert tt.wildcard_rule == "Skill(tt:*)"

    def test_threshold_not_met_under_three_skills(self) -> None:
        skills = [
            mod.LocalSkill(name="my:a", directory=Path("/x"), namespace="my"),
            mod.LocalSkill(name="my:b", directory=Path("/x"), namespace="my"),
        ]
        groups = mod.group_by_namespace(skills=skills)
        assert groups[0].threshold_met is False

    def test_drops_skills_without_namespace(self) -> None:
        skills = [
            mod.LocalSkill(name="standalone", directory=Path("/x"), namespace=None),
        ]
        assert mod.group_by_namespace(skills=skills) == []


class TestMissingSkillRules:
    def test_proposes_only_missing_skills(self) -> None:
        skills = [
            mod.LocalSkill(name="tt:db", directory=Path("/x"), namespace="tt"),
            mod.LocalSkill(name="tt:docker", directory=Path("/x"), namespace="tt"),
        ]
        existing = ["Skill(tt:db)", "Skill(other)"]

        result = mod.missing_skill_rules(skills=skills, existing_allow=existing)

        assert result == ["Skill(tt:docker)"]

    def test_namespace_wildcard_covers_explicit_skills(self) -> None:
        skills = [
            mod.LocalSkill(name="tt:db", directory=Path("/x"), namespace="tt"),
            mod.LocalSkill(name="tt:docker", directory=Path("/x"), namespace="tt"),
        ]
        existing = ["Skill(tt:*)"]

        assert (
            mod.missing_skill_rules(
                skills=skills,
                existing_allow=existing,
            )
            == []
        )
