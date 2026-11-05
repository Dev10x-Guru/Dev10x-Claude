"""Every default work-on play ends by reflecting into the vault (GH-1822).

The reflect step comes after "Verify acceptance criteria" and must never
take its place: Verify AC stays the open terminal task the supervisor
closes (GH-149), and reflection is a non-blocking step that finishes or
skips within the turn. These tests pin that shape on the plugin default
with fragment references expanded the way work-on Phase 3 expands them —
recursively, with a reference's ``condition`` applied to every step it
expands to.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dev10x.skills.playbook import load_plugin_default

_ROOT = Path(__file__).resolve().parents[3]
REFLECT = "Reflect lessons into the knowledge vault"
VERIFY_AC = "Verify acceptance criteria"
MAX_FRAGMENT_DEPTH = 3
# No Verify AC step: dev10x:reflect seeds one before it completes, so the
# task guard (GH-149) never sees reflect as the last open task.
PLAYS_WITHOUT_VERIFY_AC = ["investigation"]


@pytest.fixture(scope="module")
def playbook() -> dict[str, Any]:
    document = load_plugin_default(skill_key="work-on", plugin_roots=[_ROOT])
    assert document is not None
    return document


def _expand(
    *,
    steps: list[dict[str, Any]],
    fragments: dict[str, list[dict[str, Any]]],
    condition: str | None = None,
    depth: int = 0,
) -> list[dict[str, Any]]:
    assert depth <= MAX_FRAGMENT_DEPTH, "fragment references nest too deep"
    expanded: list[dict[str, Any]] = []
    for step in steps:
        inherited = step.get("condition", condition)
        if "fragment" in step:
            expanded.extend(
                _expand(
                    steps=fragments[step["fragment"]],
                    fragments=fragments,
                    condition=inherited,
                    depth=depth + 1,
                )
            )
            continue
        expanded.append({**step, "condition": inherited})
    return expanded


def _plays(playbook: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {
        name: _expand(steps=play["steps"], fragments=playbook["fragments"])
        for name, play in playbook["defaults"].items()
    }


def _play_names() -> list[str]:
    document = load_plugin_default(skill_key="work-on", plugin_roots=[_ROOT])
    assert document is not None
    return sorted(document["defaults"])


@pytest.mark.parametrize("play", _play_names())
def test_every_play_ends_with_reflection(playbook: dict[str, Any], play: str) -> None:
    assert _plays(playbook)[play][-1]["subject"] == REFLECT


def _reflection_predecessors(steps: list[dict[str, Any]]) -> list[tuple[str, bool]]:
    return [
        (steps[index - 1]["subject"], steps[index - 1]["condition"] == step["condition"])
        for index, step in enumerate(steps)
        if step["subject"] == REFLECT
    ]


@pytest.mark.parametrize(
    "play",
    [name for name in _play_names() if name not in PLAYS_WITHOUT_VERIFY_AC],
)
def test_reflection_directly_follows_verify_ac(playbook: dict[str, Any], play: str) -> None:
    predecessors = _reflection_predecessors(_plays(playbook)[play])

    assert predecessors
    assert set(predecessors) == {(VERIFY_AC, True)}


@pytest.mark.parametrize("play", PLAYS_WITHOUT_VERIFY_AC)
def test_plays_without_verify_ac_are_the_documented_ones(
    playbook: dict[str, Any], play: str
) -> None:
    subjects = {step["subject"] for step in _plays(playbook)[play]}

    assert VERIFY_AC not in subjects


def test_reflection_delegates_and_never_closes_verify_ac(playbook: dict[str, Any]) -> None:
    (step,) = playbook["fragments"]["session-reflection"]

    assert step["skills"] == ["dev10x:reflect"]
    assert "never mark Verify AC completed" in " ".join(step["prompt"].split())


def test_local_only_reflects_once_per_path(playbook: dict[str, Any]) -> None:
    conditions = [
        step["condition"] for step in _plays(playbook)["local-only"] if step["subject"] == REFLECT
    ]

    assert conditions == ["if-pr-decided", "if-no-pr"]
