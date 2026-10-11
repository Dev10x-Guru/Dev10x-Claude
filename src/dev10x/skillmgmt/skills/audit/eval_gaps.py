"""Detect gated skills shipping zero eval assertions (GH-835).

Background: `.claude/rules/skill-gates.md` requires every skill with a
blocking decision point (a documented ``REQUIRED: Call `AskUserQuestion```
marker in ``SKILL.md``) to ship ``evals/evals.json`` assertions that verify
the gate fires as a tool call, not plain text. Nothing previously enforced
this at audit time — a skill could add a new gate, skip the eval file
entirely, and no reviewer signal would catch it.

This module scans a ``skills/`` root and reports every **gated** skill
(one whose ``SKILL.md`` documents a `REQUIRED: Call `AskUserQuestion``
marker) that either has no ``evals/evals.json`` file at all, or has one
with zero assertions — supporting both the current dimension-referenced
format (``evals[].assertions``) and the legacy format (``checks``).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

# Matches the documented enforcement marker from skill-gates.md, tolerating
# markdown bold markers and backtick styling around AskUserQuestion.
_GATE_MARKER_RE = re.compile(
    r"REQUIRED:\s*Call\s*`{0,2}AskUserQuestion`{0,2}",
    re.IGNORECASE,
)

# A skill counts as "gated" only when SKILL.md documents the marker AND
# declares the tool in allowed-tools — a skill that merely mentions
# AskUserQuestion in prose (without the enforcement marker) is not gated.
_ALLOWED_TOOLS_ASKUSERQUESTION_RE = re.compile(r"^\s*-\s*AskUserQuestion\s*$", re.MULTILINE)


@dataclass(frozen=True)
class EvalGap:
    """A gated skill with missing or empty eval coverage."""

    skill_name: str
    skill_md_path: Path
    evals_path: Path
    classification: str  # MISSING_EVALS | EMPTY_EVALS | UNPARSEABLE_EVALS
    reason: str

    def format(self) -> str:
        return f"{self.skill_name}: [{self.classification}] {self.reason} ({self.evals_path})"


def _is_gated(skill_md_text: str) -> bool:
    """A skill is gated when SKILL.md documents the REQUIRED gate marker
    AND declares AskUserQuestion in its allowed-tools front matter."""
    if not _GATE_MARKER_RE.search(skill_md_text):
        return False
    return bool(_ALLOWED_TOOLS_ASKUSERQUESTION_RE.search(skill_md_text))


def _count_assertions(evals_data: dict) -> int:
    """Count total assertions across both the current and legacy formats."""
    total = 0

    # Dimension-referenced format (current, required for new skills).
    for eval_case in evals_data.get("evals", []):
        total += len(eval_case.get("assertions", []))

    # Legacy format — top-level "checks" per scenario, or a bare list of
    # scenarios each carrying "checks".
    for scenario in evals_data.get("scenarios", []):
        total += len(scenario.get("checks", []))
    if isinstance(evals_data.get("checks"), list):
        total += len(evals_data["checks"])

    return total


def find_skill_dirs(skills_root: Path) -> list[Path]:
    """Return every immediate skill directory under ``skills_root`` that
    ships a SKILL.md, sorted by name."""
    if not skills_root.is_dir():
        return []
    return sorted(
        (p for p in skills_root.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()),
        key=lambda p: p.name,
    )


def check_skill(skill_dir: Path) -> EvalGap | None:
    """Check a single skill directory; return an EvalGap when it is gated
    but has no (or empty) eval assertions, else None."""
    skill_md_path = skill_dir / "SKILL.md"
    skill_md_text = skill_md_path.read_text()

    if not _is_gated(skill_md_text):
        return None

    evals_path = skill_dir / "evals" / "evals.json"
    if not evals_path.is_file():
        return EvalGap(
            skill_name=skill_dir.name,
            skill_md_path=skill_md_path,
            evals_path=evals_path,
            classification="MISSING_EVALS",
            reason=(
                "SKILL.md documents a REQUIRED AskUserQuestion gate "
                "but evals/evals.json does not exist"
            ),
        )

    try:
        evals_data = json.loads(evals_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        return EvalGap(
            skill_name=skill_dir.name,
            skill_md_path=skill_md_path,
            evals_path=evals_path,
            classification="UNPARSEABLE_EVALS",
            reason=f"evals.json failed to parse: {exc}",
        )

    if not isinstance(evals_data, dict):
        return EvalGap(
            skill_name=skill_dir.name,
            skill_md_path=skill_md_path,
            evals_path=evals_path,
            classification="UNPARSEABLE_EVALS",
            reason=(f"evals.json parsed to a {type(evals_data).__name__}, expected a JSON object"),
        )

    if _count_assertions(evals_data) == 0:
        return EvalGap(
            skill_name=skill_dir.name,
            skill_md_path=skill_md_path,
            evals_path=evals_path,
            classification="EMPTY_EVALS",
            reason="evals.json exists but has zero gate assertions",
        )

    return None


def scan_skills_root(skills_root: Path) -> list[EvalGap]:
    """Scan every skill under ``skills_root`` and return all eval gaps."""
    gaps: list[EvalGap] = []
    for skill_dir in find_skill_dirs(skills_root):
        gap = check_skill(skill_dir)
        if gap is not None:
            gaps.append(gap)
    return gaps
