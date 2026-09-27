"""The catalog grants no cross-worktree git spelling it cannot honour.

GH-1268 seeded `git -C * <verb>:*` and both `--git-dir`/`--work-tree`
orderings for nine read-only verbs. GH-1472 found that a `*` before a
trailing `:*` is a literal character, so none of those 27 rules ever
matched, and a working space-form rewrite would also match
`-c core.fsmonitor=<cmd>`. They were dropped; these tests keep them — and
the verb-blind shape GH-1268 already refused — out.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


def _base_permissions(projects_yaml: Path) -> list[str]:
    data = yaml.safe_load(projects_yaml.read_text()) or {}
    return [str(rule) for rule in data.get("base_permissions", [])]


@pytest.mark.parametrize(
    "prefix",
    ["Bash(git -C ", "Bash(git --git-dir", "Bash(git --work-tree"],
)
def test_no_cross_worktree_git_rule_is_seeded(projects_yaml: Path, prefix: str) -> None:
    seeded = [rule for rule in _base_permissions(projects_yaml) if rule.startswith(prefix)]

    assert seeded == []


def test_git_c_is_not_seeded_verb_blind(projects_yaml: Path) -> None:
    assert "Bash(git -C:*)" not in _base_permissions(projects_yaml)
    assert "Bash(git -C *)" not in _base_permissions(projects_yaml)
