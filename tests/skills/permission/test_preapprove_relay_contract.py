"""Overwatch pre-approve writes only triaged rules, never a blanket (GH-1799).

The relay subagent briefed by `skills/overwatch/references/preapprove.md`
is the only writer on the pre-approve path. These tests pin the two halves
of that contract: the brief routes every target through
`permission_triage` and keeps only a `grant` verdict, and triage refuses
every shape the spread guard would hold back.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from dev10x.skills.permission.grant import Verdict, triage

_BRIEF = Path(__file__).resolve().parents[3] / "skills/overwatch/references/preapprove.md"


@pytest.fixture
def brief() -> str:
    return _BRIEF.read_text()


def test_brief_routes_every_target_through_triage(brief: str) -> None:
    assert "permission_triage(target=" in brief


def test_brief_keeps_only_grant_verdicts(brief: str) -> None:
    assert 'Keep a target only when `verdict == "grant"`' in brief


def test_brief_forbids_widening_a_rule(brief: str) -> None:
    assert "Never widen a rule" in brief


@pytest.mark.parametrize(
    "target",
    [
        "Bash(psql:*)",
        "Bash(bash:*)",
        "Edit(~/.claude/**)",
        "Read(~/**)",
        "mcp__pycharm__*",
        "mcp__pycharm__execute_terminal_command",
    ],
)
def test_triage_never_grants_a_blanket_shape(target: str, tmp_path: Path) -> None:
    result = triage(
        target=target,
        settings_files=[],
        working_dirs=[tmp_path],
        skill_map_rules=[],
    )

    assert result.verdict is not Verdict.GRANT
