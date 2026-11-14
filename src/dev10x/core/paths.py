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


def satellite_subdir(*, key: str) -> str:
    """Where a satellite's tree sits inside a checkout or marketplace clone
    of core: ``plugins/<key>`` (ADR-0034 Stage B, GH-1886)."""
    return f"{SATELLITES_DIR}/{key}"


def satellite_cache_dir(*, core_cache_dir: Path, plugin_name: str) -> Path:
    """A satellite caches beside core: ``<cache>/<publisher>/<plugin_name>``
    next to ``core_cache_dir`` = ``<cache>/<publisher>/<core>`` (GH-1886)."""
    return core_cache_dir.parent / plugin_name


def version_sort_key(name: str) -> tuple[int, ...]:
    """Lenient: a name with a non-numeric segment sorts first as ``(0,)``."""
    try:
        return tuple(int(part) for part in name.split("."))
    except ValueError:
        return (0,)


def latest_version(*, versions_dir: Path) -> str | None:
    if not versions_dir.is_dir():
        return None
    versions = sorted(versions_dir.iterdir(), key=lambda path: version_sort_key(path.name))
    return versions[-1].name if versions else None


def skill_script(*, skill: str, rel: str, plugin: str | None = None) -> str:
    """``plugin`` names the satellite a skill moved to (GH-1564); the path
    is then relative to the repo checkout rather than a plugin root."""
    path = f"{SKILLS_DIR}/{skill}/{SCRIPTS_DIR}/{rel}"
    return f"{satellite_subdir(key=plugin)}/{path}" if plugin else path


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
    beside it and is read at its own newest installed version, the policy
    permission seeding uses too (ADR-0034, GH-1886). It is trusted only when
    its manifest names ``plugin_name``. When neither exists the
    plugin-relative path is returned, so the caller's missing-script error
    names where the script was expected.
    """
    in_core = skill_script(skill=skill, rel=rel, plugin=key)
    if (plugin_root / in_core).is_file():
        return in_core
    satellite_cache = satellite_cache_dir(
        core_cache_dir=plugin_root.parent, plugin_name=plugin_name
    )
    version = latest_version(versions_dir=satellite_cache)
    if version is None:
        return in_core
    satellite_root = satellite_cache / version
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
    "latest_version",
    "satellite_cache_dir",
    "satellite_script",
    "satellite_subdir",
    "skill_files",
    "skill_roots",
    "skill_script",
    "version_sort_key",
]
