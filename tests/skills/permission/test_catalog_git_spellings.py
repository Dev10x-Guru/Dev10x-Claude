"""The cross-worktree git read spellings stay symmetric (GH-1268).

`git-dir-worktree-pinning` steers agents to `git -C <path> <verb>` when
the target checkout is not the CWD. For the life of that steer the
catalog seeded only the plumbing spelling it deprecates, so the
recommended remedy prompted while the deprecated one did not — and
`permission_catalog_gap` could not report it, because a rule that was
never catalogued cannot be reported missing.

Nothing kept the map's claim and the catalog's contents in agreement.
These tests are that something.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_READ_VERBS: frozenset[str] = frozenset(
    {
        "status",
        "log",
        "rev-parse",
        "diff",
        "branch",
        "worktree list",
        "ls-files",
        "show",
        "merge-base",
    }
)

# A `-C` rule that reaches these would let an agent rewrite another
# checkout's history from a read-shaped steer.
_MUTATING_VERBS: frozenset[str] = frozenset(
    {"push", "commit", "reset", "rebase", "merge", "checkout", "clean", "rm"}
)


def _base_permissions(projects_yaml: Path) -> list[str]:
    data = yaml.safe_load(projects_yaml.read_text()) or {}
    return [str(rule) for rule in data.get("base_permissions", [])]


def _rules_with(projects_yaml: Path, prefix: str) -> list[str]:
    return [rule for rule in _base_permissions(projects_yaml) if rule.startswith(prefix)]


@pytest.mark.parametrize("verb", sorted(_READ_VERBS))
def test_git_c_read_verb_is_seeded(projects_yaml: Path, verb: str) -> None:
    assert f"Bash(git -C * {verb}:*)" in _base_permissions(projects_yaml), (
        f"`git -C * {verb}` is steered to by git-dir-worktree-pinning but "
        "has no catalog rule — the GH-1268 contradiction"
    )


def test_git_c_is_not_seeded_verb_blind(projects_yaml: Path) -> None:
    # `Bash(git -C:*)` would also grant `git -C <path> push --force`.
    # GH-1268 names the verb-blind shape as the thing NOT to seed.
    assert "Bash(git -C:*)" not in _base_permissions(projects_yaml)
    assert "Bash(git -C *)" not in _base_permissions(projects_yaml)


@pytest.mark.parametrize("verb", sorted(_MUTATING_VERBS))
def test_git_c_grants_no_mutating_verb(projects_yaml: Path, verb: str) -> None:
    assert f"Bash(git -C * {verb}:*)" not in _base_permissions(projects_yaml), (
        f"`git -C * {verb}` mutates another checkout — route it to "
        "Dev10x:git / Dev10x:git-groom instead of seeding it"
    )


def test_both_spellings_cover_the_same_verbs(projects_yaml: Path) -> None:
    # Asymmetry IS the defect: whichever spelling is missing becomes the
    # one that prompts, and an agent steered toward it has nowhere to go.
    def verbs(prefix: str, suffix_from: int) -> set[str]:
        return {
            rule[suffix_from:-3]
            for rule in _rules_with(projects_yaml, prefix)
            if rule.endswith(":*)")
        }

    c_verbs = verbs("Bash(git -C * ", len("Bash(git -C * "))
    plumbing = {
        rule.split("--work-tree=* ", 1)[1][:-3]
        for rule in _rules_with(projects_yaml, "Bash(git --git-dir=* --work-tree=* ")
        if rule.endswith(":*)")
    }
    assert c_verbs == _READ_VERBS, f"`git -C` verb set drifted: {c_verbs ^ _READ_VERBS}"
    assert c_verbs == plumbing, f"spellings disagree on verbs: {c_verbs ^ plumbing}"
