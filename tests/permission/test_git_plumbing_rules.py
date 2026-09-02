"""Read-only git plumbing allow rules and the mid-path cell (GH-1135)."""

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

_READ_ONLY_VERBS = (
    "status",
    "log",
    "rev-parse",
    "diff",
    "branch",
    "worktree list",
    "ls-files",
    "show",
    "merge-base",
)

_MUTATING_VERBS = ("commit", "push", "reset", "rebase", "checkout", "add", "stash")


@pytest.fixture(scope="module")
def base_permissions() -> list[str]:
    data = yaml.safe_load(_CATALOG.read_text()) or {}
    return data.get("base_permissions", [])


@pytest.mark.parametrize("verb", _READ_ONLY_VERBS)
@pytest.mark.parametrize("separator", ["=", " "])
def test_read_only_verb_covered_in_both_orderings(
    base_permissions: list[str], verb: str, separator: str
):
    rule = f"Bash(git --git-dir{separator}* --work-tree{separator}* {verb}:*)"
    assert rule in base_permissions


@pytest.mark.parametrize("verb", _MUTATING_VERBS)
def test_mutating_verbs_are_not_pre_approved(base_permissions: list[str], verb: str):
    """Mutating verbs stay routed to Dev10x:git / Dev10x:git-groom."""
    plumbing = [r for r in base_permissions if "--git-dir" in r]
    assert not any(f" {verb}:" in rule for rule in plumbing)


def test_no_catch_all_git_rule_was_introduced(base_permissions: list[str]):
    """`git *` is the GH-310 footgun the prompt offers — never ship it."""
    assert "Bash(git *)" not in base_permissions
    assert "Bash(git:*)" not in base_permissions


def test_matrix_covers_the_mid_path_wildcard():
    """The rules above depend on a shape ADR-0021 left unverified."""
    assert "mid_path_star" in DEFAULT_WILDCARDS
    cells = generate_matrix().cells
    assert any(
        cell.shape.tool == "Bash" and cell.shape.wildcard == "mid_path_star" for cell in cells
    )
