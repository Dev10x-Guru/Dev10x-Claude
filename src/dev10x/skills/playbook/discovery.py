"""Locate user playbook overrides and matching plugin defaults (GH-192)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dev10x.subprocess_utils import effective_cwd

PROJECT_OVERRIDE_DIR = ".claude/Dev10x/playbooks"
GLOBAL_OVERRIDE_DIR = "~/.claude/memory/Dev10x/playbooks"


@dataclass(frozen=True)
class UserPlaybook:
    """One user playbook override on disk.

    ``skill_key`` matches the skill directory name (e.g., ``work-on``).
    ``scope`` is ``project`` for repo-local overrides and ``global`` for
    user-home overrides.
    """

    skill_key: str
    path: Path
    scope: str  # "project" | "global"


def _yaml_files(directory: Path) -> list[Path]:
    """Return ``*.yaml`` files in ``directory`` (sorted, non-recursive).

    Returns an empty list when the directory does not exist — playbook
    overrides are optional and a missing directory is not an error.
    """
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.glob("*.yaml") if p.is_file())


def find_user_playbooks(
    *,
    project_root: Path | None = None,
    home: Path | None = None,
) -> list[UserPlaybook]:
    """Find every user playbook override visible from ``project_root``.

    Searches both the project-local override directory and the global
    override directory under ``home``. ``project_root`` defaults to the
    current working directory; ``home`` defaults to ``$HOME``.
    """
    root = project_root or Path(effective_cwd() or Path.cwd())
    home_dir = home or Path(os.path.expanduser("~"))
    project_dir = root / PROJECT_OVERRIDE_DIR
    global_dir = home_dir / Path(GLOBAL_OVERRIDE_DIR.replace("~/", ""))

    found: list[UserPlaybook] = []
    for path in _yaml_files(project_dir):
        found.append(UserPlaybook(skill_key=path.stem, path=path, scope="project"))
    for path in _yaml_files(global_dir):
        found.append(UserPlaybook(skill_key=path.stem, path=path, scope="global"))
    return found


def plugin_default_path(*, skill_key: str, plugin_root: Path) -> Path:
    """Return the path to the plugin default playbook for ``skill_key``.

    The default playbook for any skill lives at
    ``<plugin_root>/skills/<skill_key>/references/playbook.yaml``.
    The path is returned whether or not it exists; callers decide how to
    handle a missing default (typically: the skill is not playbook-powered).
    """
    return plugin_root / "skills" / skill_key / "references" / "playbook.yaml"
