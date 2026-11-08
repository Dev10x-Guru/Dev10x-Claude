"""Expand the plugin-default work-on plays the way work-on Phase 3 does.

Fragment references expand recursively. A reference's ``condition``
reaches every expanded step; a step that carries its own condition keeps
it too, joined as ``<outer> and <inner>`` — neither side wins, because
dropping either one would run the step on a path one of them excludes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dev10x.skills.playbook import load_plugin_default

ROOT = Path(__file__).resolve().parents[3]
MAX_FRAGMENT_DEPTH = 3
VERIFY_AC = "Verify acceptance criteria"


def load_work_on_playbook() -> dict[str, Any]:
    document = load_plugin_default(skill_key="work-on", plugin_roots=[ROOT])
    assert document is not None
    return document


def combine_conditions(*, outer: str | None, inner: str | None) -> str | None:
    if outer and inner:
        return f"{outer} and {inner}"
    return outer or inner


def expand_steps(
    *,
    steps: list[dict[str, Any]],
    fragments: dict[str, list[dict[str, Any]]],
    condition: str | None = None,
    depth: int = 0,
) -> list[dict[str, Any]]:
    assert depth <= MAX_FRAGMENT_DEPTH, "fragment references nest too deep"
    expanded: list[dict[str, Any]] = []
    for step in steps:
        inherited = combine_conditions(outer=condition, inner=step.get("condition"))
        if "fragment" in step:
            expanded.extend(
                expand_steps(
                    steps=fragments[step["fragment"]],
                    fragments=fragments,
                    condition=inherited,
                    depth=depth + 1,
                )
            )
            continue
        expanded.append({**step, "condition": inherited})
    return expanded


def expand_plays(playbook: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {
        name: expand_steps(steps=play["steps"], fragments=playbook["fragments"])
        for name, play in playbook["defaults"].items()
    }


def play_names() -> list[str]:
    return sorted(load_work_on_playbook()["defaults"])
