"""Single resolver for skill-script paths used by ``src/`` (ADR-0034, GH-1526).

Returns the plugin-root-relative path that ``subprocess_utils`` already
resolves against the working tree or the cached install. Stage B moves
skills into ``plugins/<p>/skills/``; routing every caller through here
makes that move one edit instead of a literal sweep.

Imports nothing beyond the standard library, so the dependency-free
``bin/`` scanners can find every skill root too (GH-1564).
"""

from __future__ import annotations

import json
from pathlib import Path

PLUGIN_MANIFEST = Path(".claude-plugin") / "plugin.json"
SKILLS_DIR = "skills"
SCRIPTS_DIR = "scripts"
SATELLITES_DIR = "plugins"
SKILL_FILE = "SKILL.md"


def skill_script(*, skill: str, rel: str, plugin: str | None = None) -> str:
    """``plugin`` names the satellite a skill moved to (GH-1564); the path
    is then relative to the repo checkout rather than a plugin root."""
    path = f"{SKILLS_DIR}/{skill}/{SCRIPTS_DIR}/{rel}"
    return f"{SATELLITES_DIR}/{plugin}/{path}" if plugin else path


def satellite_script(
    *,
    plugin_root: Path,
    key: str,
    plugin_name: str,
    skill: str,
    rel: str,
) -> str:
    """A core caller reaching a script that moved to a satellite (GH-1566).

    A checkout or marketplace clone holds the satellite under core's own
    root, so the plugin-relative path is returned and stays subject to the
    working-tree preference of ``resolve_script_path``. An installed core
    sits at ``<cache>/<publisher>/<core>/<version>``; the satellite installs
    beside it at the same version, since versions move in lockstep, and is
    trusted only when its manifest names ``plugin_name``. When
    neither exists the plugin-relative path is returned, so the caller's
    missing-script error names where the script was expected.
    """
    in_core = skill_script(skill=skill, rel=rel, plugin=key)
    if (plugin_root / in_core).is_file():
        return in_core
    satellite_root = plugin_root.parent.parent / plugin_name / plugin_root.name
    beside = satellite_root / skill_script(skill=skill, rel=rel)
    if beside.is_file() and _manifest_names(root=satellite_root, plugin_name=plugin_name):
        return str(beside)
    return in_core


def _manifest_names(*, root: Path, plugin_name: str) -> bool:
    try:
        manifest = json.loads((root / PLUGIN_MANIFEST).read_text())
    except (OSError, ValueError):
        return False
    return isinstance(manifest, dict) and manifest.get("name") == plugin_name


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
    "PLUGIN_MANIFEST",
    "SATELLITES_DIR",
    "SCRIPTS_DIR",
    "SKILLS_DIR",
    "SKILL_FILE",
    "satellite_script",
    "skill_files",
    "skill_roots",
    "skill_script",
]
