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

Both digests exclude the top-level ``version`` key: release tooling bumps
it on every release, and a pin that breaks on a version bump pins the
release cadence rather than the playbook's content.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

import pytest

from dev10x.skills.playbook import load_plugin_default
from dev10x.subprocess_utils import get_plugin_root

PRE_SPLIT_SHA256 = "a9ee7911d09b680484b249271d5c427554ef68ec93f21ce04fc9e01d6d0869c3"
RESOLVED_SHA256 = "6a8db9b4d64ce1497b8094415e85368f09e488c90fb867fadcd8a4ce1cfb93c2"
VERSION_KEY = "version"

DELTA_PLAY = "structured-spec"
OPTIONAL_SINCE_SPLIT = (
    "Record ADR (if architectural decision involved)",
    "Spec-update gate (Golden Rule)",
    "Spec-sync gate before merge",
)


def _without_version(document: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key != VERSION_KEY}


def _digest(document: dict[str, Any]) -> str:
    canonical = json.dumps(_without_version(document), sort_keys=True, ensure_ascii=False)
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
