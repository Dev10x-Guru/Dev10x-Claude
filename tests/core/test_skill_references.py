"""Baseline inventory of ``dev10x:<skill>`` references (ADR-0034, GH-1531).

``tests/fixtures/skill_reference_inventory.json`` pins the reference
count per skill across skills, playbooks, evals, docs, references,
agents, commands and ``command-skill-map.yaml``. A Stage B rename PR
moves a skill's whole count to its new prefix; any other change means a
reference was added or dropped, so update the fixture in the same PR.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.core.plugin_map import skill_directories
from dev10x.core.skill_references import (
    count_references,
    references_in,
    scanned_paths,
    unknown_references,
)
from dev10x.subprocess_utils import get_plugin_root

INVENTORY_PATH = Path(__file__).parents[1] / "fixtures" / "skill_reference_inventory.json"

# `dev10x:<name>` spellings that are deliberately not skill directories.
# Adding a name here is a claim that it must NOT be renamed with a skill.
NON_SKILL_NAMES = {
    "cli": "the plugin:dev10x:cli MCP server",
    "discover": "a retired park-discover alias quoted in work-on history",
    "example": "placeholder in docs",
    "example-skill": "placeholder in docs",
    "knowledge-research": "a proposed skill in memo 006, never created",
    "my-feature": "placeholder in docs",
    "my-skill-name": "placeholder in docs",
    "nonexistent": "the error example in references/skill-invocation.md",
    "reasons-canvas": "an option ADR-0005 rejected",
    "report-work-weekly": "a personal skill hidden by skill-index/hidden.yaml",
    "skill-reinforcement": "the former name of diag-friction",
    "some-skill": "placeholder in docs",
    "target-name": "placeholder in docs",
    "ticket-foo": "placeholder in docs",
}


def _agent_names() -> list[str]:
    return [path.stem for path in (get_plugin_root() / "agents").glob("*.md")]


@pytest.fixture(scope="module")
def counts() -> dict[str, int]:
    return count_references(paths=scanned_paths(root=get_plugin_root()))


class TestRepositoryInventory:
    def test_every_reference_names_a_real_skill(self, counts: dict[str, int]) -> None:
        known = [
            *skill_directories(skills_root=get_plugin_root() / "skills"),
            *_agent_names(),
            *NON_SKILL_NAMES,
        ]

        assert unknown_references(counts=counts, skills=known) == []

    def test_every_non_skill_name_is_still_referenced(self, counts: dict[str, int]) -> None:
        assert sorted(set(NON_SKILL_NAMES) - set(counts)) == []

    def test_counts_match_the_baseline(self, counts: dict[str, int]) -> None:
        expected = json.loads(INVENTORY_PATH.read_text())

        assert counts == expected, (
            "dev10x:<skill> reference counts changed (GH-1531). If the change is "
            f"intended, replace {INVENTORY_PATH.name} with:\n" + json.dumps(counts, indent=2)
        )


class TestReferenceDetection:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Skill(dev10x:git-commit)", ["git-commit"]),
            ("use `Dev10x:git-groom` then dev10x:review.", ["git-groom", "review"]),
            ("dev10x://skills/index", []),
            ("mcp__plugin_dev10x_cli__mktmp", []),
            ("dev10x:<skill>", []),
            ("dev10x:ticket-", []),
            ("my.dev10x:fake", []),
        ],
    )
    def test_references_in(self, text: str, expected: list[str]) -> None:
        assert references_in(text=text) == expected

    def test_unknown_reference_is_flagged(self) -> None:
        counts = {"git": 2, "no-such-skill": 1}

        assert unknown_references(counts=counts, skills=["git"]) == ["no-such-skill"]

    def test_counts_aggregate_across_files(self, tmp_path: Path) -> None:
        (tmp_path / "skills" / "a").mkdir(parents=True)
        (tmp_path / "skills" / "a" / "SKILL.md").write_text("dev10x:git dev10x:git\n")
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "x.yaml").write_text("skill: dev10x:review\n")
        (tmp_path / "docs" / "ignored.txt").write_text("dev10x:git\n")

        assert count_references(paths=scanned_paths(root=tmp_path)) == {"git": 2, "review": 1}
