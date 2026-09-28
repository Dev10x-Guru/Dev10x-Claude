"""Every Dev10x estimate must come from one method (GH-1495).

ticket-scope used to carry its own human-pace Fibonacci table and
project-scope named an "estimated complexity" with no scale at all, so
the same ticket could be sized three ways. The method now lives in
`dev10x:estimate`; these checks keep each consumer delegating to it and
keep the retired human-duration scale from creeping back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parents[2]
_METHOD = _REPO_ROOT / "skills/estimate/SKILL.md"
_DELEGATION = "Skill(dev10x:estimate)"

_DELEGATING_CONSUMERS = (
    "skills/ticket-scope/instructions.md",
    "skills/project-scope/SKILL.md",
    "skills/work-on/instructions.md",
)

_TEMPLATES = (
    "skills/ticket-scope/references/business-feature-template.md",
    "skills/ticket-scope/references/technical-task-template.md",
    "skills/ticket-scope/references/bug-fix-template.md",
)


def _read(relative: str) -> str:
    return (_REPO_ROOT / relative).read_text(encoding="utf-8")


def test_method_file_exists() -> None:
    assert _METHOD.is_file()


@pytest.mark.parametrize("consumer", _DELEGATING_CONSUMERS)
def test_consumer_delegates_to_estimate_skill(consumer: str) -> None:
    assert _DELEGATION in _read(relative=consumer)


@pytest.mark.parametrize("template", _TEMPLATES)
def test_template_estimate_comes_from_estimate_skill(template: str) -> None:
    assert "dev10x:estimate" in _read(relative=template)


@pytest.mark.parametrize(
    "line_item",
    ["Agent implementation", "Human review", "Review wait", "Testing", "Documentation"],
)
def test_method_names_every_line_item(line_item: str) -> None:
    assert f"**{line_item}**" in _METHOD.read_text(encoding="utf-8")


def test_ticket_scope_no_longer_carries_human_duration_scale() -> None:
    text = _read(relative="skills/ticket-scope/instructions.md")

    assert "| Points | Complexity | Duration |" not in text
