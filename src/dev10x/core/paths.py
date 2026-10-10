"""Single resolver for skill-script paths used by ``src/`` (ADR-0034, GH-1526).

Returns the plugin-root-relative path that ``subprocess_utils`` already
resolves against the working tree or the cached install. Stage B moves
skills into ``plugins/<p>/skills/``; routing every caller through here
makes that move one edit instead of a literal sweep.
"""

from __future__ import annotations

SKILLS_DIR = "skills"
SCRIPTS_DIR = "scripts"


def skill_script(*, skill: str, rel: str) -> str:
    return f"{SKILLS_DIR}/{skill}/{SCRIPTS_DIR}/{rel}"


__all__ = ["SCRIPTS_DIR", "SKILLS_DIR", "skill_script"]
