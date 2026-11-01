"""Single resolver for skill-script paths used by ``src/`` (ADR-0034, GH-1526).

Returns the plugin-root-relative path that ``subprocess_utils`` already
resolves against the working tree or the cached install. Stage B moves
skills into ``plugins/<p>/skills/``; routing every caller through here
makes that move one edit instead of a literal sweep.

Imports nothing beyond the standard library, so the dependency-free
``bin/`` scanners can find every skill root too (GH-1564).
"""

from __future__ import annotations

from pathlib import Path

SKILLS_DIR = "skills"
SCRIPTS_DIR = "scripts"
SATELLITES_DIR = "plugins"
SKILL_FILE = "SKILL.md"


def skill_script(*, skill: str, rel: str, plugin: str | None = None) -> str:
    """``plugin`` names the satellite a skill moved to (GH-1564); the path
    is then relative to the repo checkout rather than a plugin root."""
    path = f"{SKILLS_DIR}/{skill}/{SCRIPTS_DIR}/{rel}"
    return f"{SATELLITES_DIR}/{plugin}/{path}" if plugin else path


def skill_roots(*, repo_root: Path) -> list[Path]:
    satellites = sorted(
        path for path in (repo_root / SATELLITES_DIR).glob(f"*/{SKILLS_DIR}") if path.is_dir()
    )
    return [repo_root / SKILLS_DIR, *satellites]


def skill_files(*, repo_root: Path) -> list[Path]:
    return [
        skill_file
        for root in skill_roots(repo_root=repo_root)
        for skill_file in sorted(root.glob(f"*/{SKILL_FILE}"))
    ]


__all__ = [
    "SATELLITES_DIR",
    "SCRIPTS_DIR",
    "SKILLS_DIR",
    "SKILL_FILE",
    "skill_files",
    "skill_roots",
    "skill_script",
]
