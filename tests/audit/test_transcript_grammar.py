"""GH-588: the transcript grammar has one source of truth.

``dev10x.audit.transcript_grammar`` owns the regexes. ``permissions_model``
imports them (identity check). ``analyze_actions`` is a PEP 723 standalone
uv-script that mirrors them inline; these tests assert the mirror never
drifts from the source of truth.
"""

from __future__ import annotations

import pytest

grammar = pytest.importorskip("dev10x.audit.transcript_grammar", reason="dev10x not installed")
from dev10x.audit import permissions_model  # noqa: E402
from dev10x.skills.audit import analyze_actions  # noqa: E402

NAMES = ["TURN_RE", "TOOL_RE", "TOOL_INPUT_BLOCK_RE"]


@pytest.mark.parametrize("name", NAMES)
def test_permissions_model_reuses_source_of_truth(name: str) -> None:
    # Imported, not redefined — same compiled object, so it cannot diverge.
    assert getattr(permissions_model, name) is getattr(grammar, name)


@pytest.mark.parametrize("name", NAMES)
def test_analyze_actions_mirror_matches_source(name: str) -> None:
    mirror = getattr(analyze_actions, name)
    canonical = getattr(grammar, name)
    assert mirror.pattern == canonical.pattern
    assert mirror.flags == canonical.flags


def test_turn_re_exposes_trailing_group() -> None:
    # The unified TURN_RE keeps the trailing group analyze_actions relies on
    # for [CORRECTION] detection; permissions_model simply ignores it.
    match = grammar.TURN_RE.search("## Turn 7 [12:00:00] USER **[CORRECTION]**")
    assert match is not None
    assert match.group(1) == "7"
    assert match.group(3) == "USER"
    assert "[CORRECTION]" in match.group(4)
