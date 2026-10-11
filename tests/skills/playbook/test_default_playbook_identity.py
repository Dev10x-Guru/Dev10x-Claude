"""The resolved shared default playbook is pinned (GH-1555, ADR-0034 A3).

The shared default splits into a core mechanism file plus per-plugin
fragments. Whatever the split, ``load_plugin_default`` must hand
``playbook diff`` and work-on exactly the document the one-file original
declared. The hash below was computed from the pre-split
``skills/playbook/references/playbook.yaml``; steps are lists, so their
order is part of what it pins.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from dev10x.skills.playbook import load_plugin_default
from dev10x.subprocess_utils import get_plugin_root

RESOLVED_SHA256 = "0cd0de092fb5c7a3507835463491af468a3c9ac5abc32249e844d449048d81c5"


def _digest(document: dict[str, Any]) -> str:
    canonical = json.dumps(document, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def resolved() -> dict[str, Any]:
    document = load_plugin_default(skill_key="work-on", plugin_roots=[get_plugin_root()])
    assert document is not None
    return document


@pytest.mark.parametrize("skill_key", ["work-on", "playbook"])
def test_shared_default_keys_resolve_identically(skill_key: str, resolved: dict[str, Any]) -> None:
    document = load_plugin_default(skill_key=skill_key, plugin_roots=[get_plugin_root()])

    assert document == resolved


def test_resolved_default_matches_the_pre_split_golden(resolved: dict[str, Any]) -> None:
    assert _digest(resolved) == RESOLVED_SHA256, (
        "the resolved default playbook changed (GH-1555). An intended change "
        f"updates RESOLVED_SHA256 to {_digest(resolved)}"
    )
