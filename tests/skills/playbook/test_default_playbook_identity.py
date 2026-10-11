"""The resolved shared default playbook is pinned (GH-1555, ADR-0034 A3).

The shared default splits into a core mechanism file plus per-plugin
fragments. Whatever the split, ``load_plugin_default`` must hand
``playbook diff`` and work-on exactly the document the one-file original
declared. ``PRE_SPLIT_SHA256`` was computed from the unsplit
``skills/playbook/references/playbook.yaml``; steps are lists, so their
order is part of what it pins.

The one intended change since is ``optional: true`` on the three
structured-spec steps that delegate to scoping skills, so they drop out
when scoping is not installed. The golden is compared with exactly that
delta removed, and the delta is asserted on its own.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

import pytest

from dev10x.skills.playbook import load_plugin_default
from dev10x.subprocess_utils import get_plugin_root

PRE_SPLIT_SHA256 = "0cd0de092fb5c7a3507835463491af468a3c9ac5abc32249e844d449048d81c5"
RESOLVED_SHA256 = "45d198d7bc59616c52cfba507f2df9d10242e31a6ec342db9b184c78338b1f9b"

DELTA_PLAY = "structured-spec"
OPTIONAL_SINCE_SPLIT = (
    "Record ADR (if architectural decision involved)",
    "Spec-update gate (Golden Rule)",
    "Spec-sync gate before merge",
)


def _digest(document: dict[str, Any]) -> str:
    canonical = json.dumps(document, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _steps_by_subject(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    steps = document["defaults"][DELTA_PLAY]["steps"]
    return {step["subject"]: step for step in steps if "subject" in step}


def _without_delta(document: dict[str, Any]) -> dict[str, Any]:
    stripped = copy.deepcopy(document)
    steps = _steps_by_subject(stripped)
    for subject in OPTIONAL_SINCE_SPLIT:
        del steps[subject]["optional"]
    return stripped


@pytest.fixture(scope="module")
def resolved() -> dict[str, Any]:
    document = load_plugin_default(skill_key="work-on", plugin_roots=[get_plugin_root()])
    assert document is not None
    return document


@pytest.mark.parametrize("skill_key", ["work-on", "playbook"])
def test_shared_default_keys_resolve_identically(skill_key: str, resolved: dict[str, Any]) -> None:
    document = load_plugin_default(skill_key=skill_key, plugin_roots=[get_plugin_root()])

    assert document == resolved


def test_split_reproduces_the_pre_split_document(resolved: dict[str, Any]) -> None:
    assert _digest(_without_delta(resolved)) == PRE_SPLIT_SHA256


@pytest.mark.parametrize("subject", OPTIONAL_SINCE_SPLIT)
def test_scoping_steps_are_optional(subject: str, resolved: dict[str, Any]) -> None:
    assert _steps_by_subject(resolved)[subject]["optional"] is True


def test_resolved_default_is_pinned(resolved: dict[str, Any]) -> None:
    assert _digest(resolved) == RESOLVED_SHA256, (
        "the resolved default playbook changed (GH-1555). An intended change "
        f"updates RESOLVED_SHA256 to {_digest(resolved)}"
    )
