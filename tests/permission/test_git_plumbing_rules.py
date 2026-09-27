"""Git plumbing allow rules and the mid-path cell (GH-1135, GH-1472).

GH-1135 seeded `git --git-dir=* --work-tree=* <verb>:*` for read-only
verbs. GH-1472 dropped them: a `*` before `:*` is literal, so they never
matched.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dev10x.skills.permission_investigator.matrix import (
    DEFAULT_WILDCARDS,
    generate_matrix,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CATALOG = _REPO_ROOT / "skills" / "upgrade-cleanup" / "projects.yaml"


@pytest.fixture(scope="module")
def base_permissions() -> list[str]:
    data = yaml.safe_load(_CATALOG.read_text()) or {}
    return data.get("base_permissions", [])


def test_no_plumbing_rule_is_seeded(base_permissions: list[str]):
    assert [r for r in base_permissions if "--git-dir" in r or "--work-tree" in r] == []


def test_no_catch_all_git_rule_was_introduced(base_permissions: list[str]):
    """`git *` is the GH-310 footgun the prompt offers — never ship it."""
    assert "Bash(git *)" not in base_permissions
    assert "Bash(git:*)" not in base_permissions


def test_matrix_covers_the_mid_path_wildcard():
    """The investigator keeps measuring the shape GH-1472 found unmatchable."""
    assert "mid_path_star" in DEFAULT_WILDCARDS
    cells = generate_matrix().cells
    assert any(
        cell.shape.tool == "Bash" and cell.shape.wildcard == "mid_path_star" for cell in cells
    )
