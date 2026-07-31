"""Tests for the eval-gap detector (GH-835)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.skills.audit import eval_gaps as mod

GATED_SKILL_MD = """---
name: Dev10x:demo
allowed-tools:
  - AskUserQuestion
  - Read
---

# Demo

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
Options:
- Yes
- No
"""

UNGATED_SKILL_MD = """---
name: Dev10x:demo
allowed-tools:
  - Read
---

# Demo

Just reads a file. No decision gates here.
"""

GATED_NO_ALLOWED_TOOLS_MD = """---
name: Dev10x:demo
allowed-tools:
  - Read
---

# Demo

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
"""


def _write_skill(root: Path, name: str, skill_md: str) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(skill_md)
    return skill_dir


def _write_evals(skill_dir: Path, data: dict) -> Path:
    evals_dir = skill_dir / "evals"
    evals_dir.mkdir(parents=True, exist_ok=True)
    evals_path = evals_dir / "evals.json"
    evals_path.write_text(json.dumps(data))
    return evals_path


@pytest.fixture
def skills_root(tmp_path: Path) -> Path:
    root = tmp_path / "skills"
    root.mkdir()
    return root


class TestIsGated:
    def test_marker_and_allowed_tools_present_is_gated(self) -> None:
        assert mod._is_gated(GATED_SKILL_MD) is True

    def test_no_marker_is_not_gated(self) -> None:
        assert mod._is_gated(UNGATED_SKILL_MD) is False

    def test_marker_without_allowed_tools_entry_is_not_gated(self) -> None:
        assert mod._is_gated(GATED_NO_ALLOWED_TOOLS_MD) is False


class TestCountAssertions:
    def test_dimension_referenced_format(self) -> None:
        data = {
            "evals": [
                {"assertions": [{"dimension": "d1", "check": "tool_called"}]},
                {"assertions": [{"dimension": "d1", "check": "behavioral"}, {"dimension": "d2"}]},
            ]
        }
        assert mod._count_assertions(data) == 3

    def test_legacy_checks_format(self) -> None:
        data = {"checks": [{"type": "tool_called"}, {"type": "behavioral"}]}
        assert mod._count_assertions(data) == 2

    def test_legacy_scenarios_format(self) -> None:
        data = {"scenarios": [{"checks": [{"type": "tool_called"}]}]}
        assert mod._count_assertions(data) == 1

    def test_empty_evals_is_zero(self) -> None:
        assert mod._count_assertions({"evals": []}) == 0
        assert mod._count_assertions({}) == 0


class TestCheckSkill:
    def test_ungated_skill_has_no_gap(self, skills_root: Path) -> None:
        skill_dir = _write_skill(skills_root, "demo", UNGATED_SKILL_MD)
        assert mod.check_skill(skill_dir) is None

    def test_gated_skill_missing_evals_file_is_gap(self, skills_root: Path) -> None:
        skill_dir = _write_skill(skills_root, "demo", GATED_SKILL_MD)
        gap = mod.check_skill(skill_dir)
        assert gap is not None
        assert gap.classification == "MISSING_EVALS"
        assert gap.skill_name == "demo"

    def test_gated_skill_with_empty_evals_is_gap(self, skills_root: Path) -> None:
        skill_dir = _write_skill(skills_root, "demo", GATED_SKILL_MD)
        _write_evals(skill_dir, {"skill_name": "Dev10x:demo", "evals": []})
        gap = mod.check_skill(skill_dir)
        assert gap is not None
        assert gap.classification == "EMPTY_EVALS"

    def test_gated_skill_with_real_assertions_has_no_gap(self, skills_root: Path) -> None:
        skill_dir = _write_skill(skills_root, "demo", GATED_SKILL_MD)
        _write_evals(
            skill_dir,
            {
                "skill_name": "Dev10x:demo",
                "evals": [
                    {
                        "id": "gate1",
                        "assertions": [
                            {
                                "dimension": "d1",
                                "check": "tool_called",
                                "tool": "AskUserQuestion",
                            }
                        ],
                    }
                ],
            },
        )
        assert mod.check_skill(skill_dir) is None

    def test_gated_skill_with_unparseable_evals_is_gap(self, skills_root: Path) -> None:
        skill_dir = _write_skill(skills_root, "demo", GATED_SKILL_MD)
        evals_dir = skill_dir / "evals"
        evals_dir.mkdir(parents=True)
        (evals_dir / "evals.json").write_text("{not valid json")
        gap = mod.check_skill(skill_dir)
        assert gap is not None
        assert gap.classification == "UNPARSEABLE_EVALS"

    def test_gap_format_includes_skill_name_and_classification(self, skills_root: Path) -> None:
        skill_dir = _write_skill(skills_root, "demo", GATED_SKILL_MD)
        gap = mod.check_skill(skill_dir)
        assert gap is not None
        formatted = gap.format()
        assert "demo" in formatted
        assert "MISSING_EVALS" in formatted


class TestFindSkillDirs:
    def test_returns_only_dirs_with_skill_md(self, skills_root: Path) -> None:
        _write_skill(skills_root, "has-md", UNGATED_SKILL_MD)
        (skills_root / "no-md").mkdir()
        dirs = mod.find_skill_dirs(skills_root)
        assert [d.name for d in dirs] == ["has-md"]

    def test_missing_root_returns_empty(self, tmp_path: Path) -> None:
        assert mod.find_skill_dirs(tmp_path / "nonexistent") == []


class TestScanSkillsRoot:
    def test_aggregates_gaps_across_skills(self, skills_root: Path) -> None:
        _write_skill(skills_root, "gated-missing", GATED_SKILL_MD)
        _write_skill(skills_root, "ungated", UNGATED_SKILL_MD)
        gated_ok = _write_skill(skills_root, "gated-ok", GATED_SKILL_MD)
        _write_evals(
            gated_ok,
            {
                "evals": [
                    {"assertions": [{"dimension": "d1", "check": "tool_called"}]},
                ]
            },
        )

        gaps = mod.scan_skills_root(skills_root)

        assert {g.skill_name for g in gaps} == {"gated-missing"}
