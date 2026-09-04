"""Shared fixtures for the permission-skill tests (GH-1190).

Eight modules in this directory re-derived the shipped catalog path and
re-declared the same ``settings_file`` fixture. Two of them derived the
repo root a different way from the rest, which is exactly the drift the
production-side resolver work removes — so the tests get one definition
too.

The catalog path goes through
:func:`~dev10x.skills.permission.catalog_paths.shipped_projects_catalog`
so the tests exercise the same helper the four call sites use.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.skills.permission.catalog_paths import shipped_projects_catalog

REPO_ROOT = Path(__file__).resolve().parents[3]
PROJECTS_YAML = shipped_projects_catalog(plugin_root=REPO_ROOT)


@pytest.fixture
def projects_yaml() -> Path:
    """Path to the shipped ``skills/upgrade-cleanup/projects.yaml``."""
    assert PROJECTS_YAML is not None
    return PROJECTS_YAML


@pytest.fixture
def settings_file(tmp_path: Path) -> Path:
    """An empty ``settings.local.json`` for the writers to act on."""
    path = tmp_path / "settings.local.json"
    path.write_text("{}\n")
    return path
