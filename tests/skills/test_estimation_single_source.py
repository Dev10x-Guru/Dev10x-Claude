"""Every Dev10x estimate must come from one method (GH-1495).

ticket-scope used to carry its own human-pace Fibonacci table and
project-scope named an "estimated complexity" with no scale at all, so
the same ticket could be sized three ways. The method now lives in
`references/estimation.md`; these checks keep each consumer pointing at
it and keep the retired human-duration scale from creeping back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parents[2]
_METHOD = "references/estimation.md"

_CONSUMERS = (
    "skills/estimate/SKILL.md",
    "skills/ticket-scope/instructions.md",
    "skills/project-scope/SKILL.md",
    "skills/work-on/instructions.md",
    "hooks/scripts/session-guidance.md",
)


def test_method_file_exists() -> None:
    assert (_REPO_ROOT / _METHOD).is_file()


@pytest.mark.parametrize("consumer", _CONSUMERS)
def test_consumer_points_at_shared_method(consumer: str) -> None:
    text = (_REPO_ROOT / consumer).read_text(encoding="utf-8")

    assert _METHOD in text


@pytest.mark.parametrize(
    "line_item",
    ["Agent implementation", "Human review", "Review wait", "Testing", "Documentation"],
)
def test_method_names_every_line_item(line_item: str) -> None:
    text = (_REPO_ROOT / _METHOD).read_text(encoding="utf-8")

    assert f"**{line_item}**" in text


def test_ticket_scope_no_longer_carries_human_duration_scale() -> None:
    text = (_REPO_ROOT / "skills/ticket-scope/instructions.md").read_text(encoding="utf-8")

    assert "| Points | Complexity | Duration |" not in text
