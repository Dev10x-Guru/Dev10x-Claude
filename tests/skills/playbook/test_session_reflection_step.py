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

from typing import Any

import pytest

from tests.skills.playbook.play_expansion import (
    VERIFY_AC,
    combine_conditions,
    expand_plays,
    play_names,
)

REFLECT = "Reflect lessons into the knowledge vault"
# No Verify AC step: dev10x:reflect seeds one before it completes, so the
# task guard (GH-149) never sees reflect as the last open task.
PLAYS_WITHOUT_VERIFY_AC = ["investigation"]


@pytest.mark.parametrize("play", play_names())
def test_every_play_ends_with_reflection(playbook: dict[str, Any], play: str) -> None:
    assert expand_plays(playbook)[play][-1]["subject"] == REFLECT


def _reflection_predecessors(steps: list[dict[str, Any]]) -> list[tuple[str, bool]]:
    return [
        (steps[index - 1]["subject"], steps[index - 1]["condition"] == step["condition"])
        for index, step in enumerate(steps)
        if step["subject"] == REFLECT
    ]


@pytest.mark.parametrize(
    "play",
    [name for name in play_names() if name not in PLAYS_WITHOUT_VERIFY_AC],
)
def test_reflection_directly_follows_verify_ac(playbook: dict[str, Any], play: str) -> None:
    predecessors = _reflection_predecessors(expand_plays(playbook)[play])

    assert predecessors
    assert set(predecessors) == {(VERIFY_AC, True)}


@pytest.mark.parametrize("play", PLAYS_WITHOUT_VERIFY_AC)
def test_plays_without_verify_ac_are_the_documented_ones(
    playbook: dict[str, Any], play: str
) -> None:
    subjects = {step["subject"] for step in expand_plays(playbook)[play]}

    assert VERIFY_AC not in subjects


def test_reflection_delegates_and_never_closes_verify_ac(playbook: dict[str, Any]) -> None:
    (step,) = playbook["fragments"]["session-reflection"]

    assert step["skills"] == ["dev10x:reflect"]
    assert "never mark Verify AC completed" in " ".join(step["prompt"].split())


def test_local_only_reflects_once_per_path(playbook: dict[str, Any]) -> None:
    conditions = [
        step["condition"]
        for step in expand_plays(playbook)["local-only"]
        if step["subject"] == REFLECT
    ]

    assert conditions == ["if-pr-decided", "if-no-pr"]


@pytest.mark.parametrize(
    ("outer", "inner", "expected"),
    [
        (None, None, None),
        ("if-pr-decided", None, "if-pr-decided"),
        (None, "solo-maintainer", "solo-maintainer"),
        ("if-pr-decided", "solo-maintainer", "if-pr-decided and solo-maintainer"),
    ],
)
def test_reference_and_step_conditions_both_apply(
    outer: str | None, inner: str | None, expected: str | None
) -> None:
    assert combine_conditions(outer=outer, inner=inner) == expected


def test_conditioned_step_inside_conditioned_reference_keeps_both(
    playbook: dict[str, Any],
) -> None:
    (merge,) = [
        step for step in expand_plays(playbook)["local-only"] if step["subject"] == "Merge PR"
    ]

    assert merge["condition"] == "if-pr-decided and solo-maintainer"
