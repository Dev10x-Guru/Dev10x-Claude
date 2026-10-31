"""A fixup-only groom auto-advances under an autonomous posture (GH-1656).

git-groom told callers to send ``destructive`` to the ``history_rewrite``
gate, while its ``auto-advance-if-safe`` toggle reads only
``provably_safe``. The unread key left the safe flag at ``False``, so an
autosquash the skill calls deterministic resolved to ``ask`` on every
session. These checks resolve the gate with exactly what the skill
documents, so the doc and the predicate cannot drift apart again.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest

from dev10x.domain.gate_policy import BASELINE_PRESET, GateContext, GateEffect, resolve_gate

_REPO_ROOT = Path(__file__).parents[3]
_GROOM = _REPO_ROOT / "skills/git-groom/instructions.md"
_VERIFY = _REPO_ROOT / "skills/verify-acc-dod/SKILL.md"
_DOCUMENTED_CALL = re.compile(r'resolve_gate\(gate="history_rewrite",\s*context=\{"(\w+)"')


@pytest.fixture(scope="module")
def documented_key() -> str:
    found = _DOCUMENTED_CALL.search(_GROOM.read_text(encoding="utf-8"))
    assert found is not None
    return found.group(1)


def test_documented_key_is_a_gate_context_field(documented_key: str) -> None:
    assert documented_key in {field.name for field in dataclasses.fields(GateContext)}


@pytest.mark.parametrize(
    ("safe", "expected_effect"),
    [(True, GateEffect.AUTO_ADVANCE), (False, GateEffect.ASK)],
)
def test_documented_call_resolves_under_afk(
    documented_key: str,
    safe: bool,
    expected_effect: GateEffect,
) -> None:
    resolution = resolve_gate(
        gate="history_rewrite",
        context=GateContext(**{documented_key: safe}),
        preset=BASELINE_PRESET,
        overlays=["solo-maintainer", "afk"],
    )

    assert resolution.effect is expected_effect


def test_failing_fixup_check_routes_back_to_groom() -> None:
    text = _VERIFY.read_text(encoding="utf-8")

    assert 'Go back on "No fixup commits"' in text
    assert "Skill(dev10x:git-groom)" in text
