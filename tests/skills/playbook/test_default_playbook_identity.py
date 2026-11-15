"""The resolved shared default playbook is pinned (GH-1555, ADR-0034 A3).

The shared default splits into a core mechanism file plus per-plugin
fragments, and ``load_plugin_default`` must hand ``playbook diff`` and
work-on one resolved document. Steps are lists, so their order is part of
what the digest pins.

The pre-split golden that proved the split lossless was retired once the
plays changed on purpose (GH-1665): a hash of the one-file original cannot
follow an intended content edit.

The digest excludes the top-level ``version`` key: release tooling bumps
it on every release, and a pin that breaks on a version bump pins the
release cadence rather than the playbook's content.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from dev10x.core.skills.playbook import installed_plugin_roots, load_plugin_default
from dev10x.core.subprocess_utils import get_plugin_root

RESOLVED_SHA256 = "6e81311423e0c49012a796d26e1cc731f02573f1b025b3da029f638f85db67ae"
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


@pytest.fixture(scope="module")
def resolved() -> dict[str, Any]:
    document = load_plugin_default(skill_key="work-on", plugin_roots=_plugin_roots())
    assert document is not None
    return document


def _plugin_roots() -> list[Path]:
    return installed_plugin_roots(core_root=get_plugin_root())


@pytest.mark.parametrize("skill_key", ["work-on", "playbook"])
def test_shared_default_keys_resolve_identically(skill_key: str, resolved: dict[str, Any]) -> None:
    document = load_plugin_default(skill_key=skill_key, plugin_roots=_plugin_roots())

    assert document == resolved


@pytest.mark.parametrize("subject", OPTIONAL_SINCE_SPLIT)
def test_scoping_steps_are_optional(subject: str, resolved: dict[str, Any]) -> None:
    assert _steps_by_subject(resolved)[subject]["optional"] is True


def test_resolved_default_is_pinned(resolved: dict[str, Any]) -> None:
    assert _digest(resolved) == RESOLVED_SHA256, (
        "the resolved default playbook changed (GH-1555). An intended change "
        f"updates RESOLVED_SHA256 to {_digest(resolved)}"
    )
