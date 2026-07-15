"""No shipped permission-rule surface may declare a Write(path) rule.

Claude Code file-permission checks match Edit(path) rules only;
Write(path) rules are ignored and warned about at session start, and
Edit(path) covers all file-editing tools (GH-862). This regression
test pins every place Dev10x *declares* file-permission rules so a
future edit cannot reintroduce a Write(path) grant:

- the baseline-permissions catalog groups,
- the upgrade-cleanup ``base_permissions`` seed list,
- every skill's ``allowed-tools`` front matter.

It also confirms the doctor deprecations catalog carries the
Write -> Edit migration entry that rewrites already-seeded user rules.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import dev10x.skills.permission as permission_pkg
from dev10x.skills.permission import doctor

REPO_ROOT = Path(permission_pkg.__file__).resolve().parents[4]
CATALOG = Path(permission_pkg.__file__).parent / "baseline-permissions.yaml"
PROJECTS_YAML = REPO_ROOT / "skills" / "upgrade-cleanup" / "projects.yaml"
SKILLS_DIR = REPO_ROOT / "skills"


def _is_write_rule(rule: object) -> bool:
    return isinstance(rule, str) and rule.startswith("Write(")


def _skill_files() -> list[Path]:
    return sorted(SKILLS_DIR.glob("*/SKILL.md"))


def _allowed_tools(skill_md: Path) -> list[str]:
    text = skill_md.read_text()
    if not text.startswith("---"):
        return []
    _, front_matter, _ = text.split("---", 2)
    data = yaml.safe_load(front_matter) or {}
    tools = data.get("allowed-tools") or []
    return [t for t in tools if isinstance(t, str)]


class TestBaselineCatalogHasNoWriteRules:
    def test_no_group_declares_a_write_rule(self) -> None:
        groups = yaml.safe_load(CATALOG.read_text())["groups"]
        offenders = [
            f"{name}: {rule}"
            for name, group in groups.items()
            for rule in group.get("rules", [])
            if _is_write_rule(rule)
        ]
        assert offenders == [], f"Write(path) rules must be Edit(path): {offenders}"


class TestProjectsSeedHasNoWriteRules:
    def test_base_permissions_declare_no_write_rule(self) -> None:
        data = yaml.safe_load(PROJECTS_YAML.read_text())
        offenders = [r for r in data.get("base_permissions", []) if _is_write_rule(r)]
        assert offenders == [], f"Write(path) rules must be Edit(path): {offenders}"


class TestSkillAllowedToolsHaveNoWriteRules:
    @pytest.mark.parametrize("skill_md", _skill_files(), ids=lambda p: p.parent.name)
    def test_allowed_tools_declare_no_write_rule(self, skill_md: Path) -> None:
        offenders = [t for t in _allowed_tools(skill_md) if _is_write_rule(t)]
        assert offenders == [], f"{skill_md.parent.name} allowed-tools: {offenders}"


class TestWriteToEditDeprecationShipped:
    def test_catalog_has_write_to_edit_rewrite(self) -> None:
        catalog = doctor.load_catalog()
        rewrites = [
            entry
            for entry in catalog.deprecations
            if entry.get("action") == "rewrite" and entry.get("replacement") == "Edit("
        ]
        assert rewrites, "missing Write( -> Edit( rewrite deprecation"

    def test_shipped_catalog_rewrites_write_to_edit(self) -> None:
        catalog = doctor.load_catalog()
        new_rules, outcomes = doctor.apply_deprecations(
            ["Write(/tmp/Dev10x/git/**)"],
            catalog=catalog,
        )
        assert new_rules == ["Edit(/tmp/Dev10x/git/**)"]
        assert outcomes[0].action == "rewrite"
        assert outcomes[0].replacement == "Edit(/tmp/Dev10x/git/**)"

    def test_shipped_catalog_dedupes_write_onto_existing_edit(self) -> None:
        catalog = doctor.load_catalog()
        new_rules, _ = doctor.apply_deprecations(
            ["Edit(/tmp/Dev10x/git/**)", "Write(/tmp/Dev10x/git/**)"],
            catalog=catalog,
        )
        assert new_rules == ["Edit(/tmp/Dev10x/git/**)"]
