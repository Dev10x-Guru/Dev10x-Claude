"""GH-1026: the business play is a light UI-change-to-PR profile.

It must reach an open PR through the shipping kernel's own skills, in
the kernel's order, and must not expose the developer-only steps —
history grooming and merging stay with a developer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dev10x.skills.playbook import load_plugin_default
from dev10x.subprocess_utils import get_plugin_root
from dev10x.teach.skill_index.builder import extract_front_matter

FRAGMENT = "business-change"
KERNEL_SKILL_SEQUENCE = [
    "dev10x:ticket-branch",
    "dev10x:git-commit",
    "dev10x:gh-pr-create",
    "dev10x:gh-pr-monitor",
    "dev10x:gh-pr-respond",
    "dev10x:verify-acc-dod",
]
DEVELOPER_ONLY_SKILLS = {
    "dev10x:git-groom",
    "dev10x:gh-pr-merge",
    "dev10x:review",
    "dev10x:review-fix",
}
PREVIEW_STEP = "Preview the change"
COMMIT_STEP = "Commit the change"


def _shipped_skill_names(*, root: Path) -> set[str]:
    manifests = [*root.glob("skills/*/SKILL.md"), *root.glob("plugins/*/skills/*/SKILL.md")]
    front_matters = [extract_front_matter(manifest.read_text()) or {} for manifest in manifests]
    return {str(front_matter.get("name")) for front_matter in front_matters}


@pytest.fixture(scope="module")
def document() -> dict[str, Any]:
    loaded = load_plugin_default(skill_key="work-on", plugin_roots=[get_plugin_root()])
    assert loaded is not None, "the shared default work-on playbook did not load"
    return loaded


@pytest.fixture(scope="module")
def steps(document: dict[str, Any]) -> list[dict[str, Any]]:
    return document["fragments"][FRAGMENT]


@pytest.fixture(scope="module")
def skill_sequence(steps: list[dict[str, Any]]) -> list[str]:
    return [skill for step in steps for skill in step.get("skills", [])]


@pytest.fixture(scope="module")
def subjects(steps: list[dict[str, Any]]) -> list[str]:
    return [step.get("subject") or f"fragment:{step['fragment']}" for step in steps]


@pytest.fixture(scope="module")
def missing_skills(skill_sequence: list[str]) -> set[str]:
    return set(skill_sequence) - _shipped_skill_names(root=get_plugin_root())


class TestBusinessChangeFragment:
    def test_runs_the_kernel_skills_in_order(self, skill_sequence: list[str]) -> None:
        assert skill_sequence == KERNEL_SKILL_SEQUENCE

    def test_exposes_no_developer_only_skill(self, skill_sequence: list[str]) -> None:
        assert set(skill_sequence) & DEVELOPER_ONLY_SKILLS == set()

    def test_previews_before_committing(self, subjects: list[str]) -> None:
        assert subjects[subjects.index(COMMIT_STEP) - 1] == PREVIEW_STEP, (
            f"'{PREVIEW_STEP}' must come right before '{COMMIT_STEP}'; got {subjects}"
        )

    def test_every_skill_ships_with_the_plugin(self, missing_skills: set[str]) -> None:
        assert missing_skills == set()

    def test_business_play_is_the_fragment(self, document: dict[str, Any]) -> None:
        assert document["defaults"]["business"]["steps"] == [{"fragment": FRAGMENT}]
