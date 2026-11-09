"""FrictionYamlDocument.effective and load_checkout_prefs — defaults under the first match."""

from __future__ import annotations

from pathlib import Path

import pytest
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.documents.friction_yaml import FrictionYamlDocument, load_checkout_prefs

FRICTION_YAML = (
    "defaults:\n"
    "  tracker: linear\n"
    "  ide: none\n"
    "projects:\n"
    "  - match: ['*/feature-x']\n"
    "    tracker: jira\n"
    "  - match: ['*/repo']\n"
    "    tracker: github\n"
)


@pytest.fixture(autouse=True)
def friction_yaml() -> None:
    path = Dev10xConfigDir.friction_yaml()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(FRICTION_YAML)


@pytest.mark.parametrize(
    ("toplevel", "fallbacks", "expected"),
    [
        ("/work/feature-x", (), {"tracker": "jira", "ide": "none"}),
        ("/work/wt/unrelated", ("/work/repo",), {"tracker": "github", "ide": "none"}),
        ("/work/feature-x", ("/work/repo",), {"tracker": "jira", "ide": "none"}),
        ("/work/other", ("/work/also-other",), {"tracker": "linear", "ide": "none"}),
    ],
)
def test_effective_layers_defaults_under_the_first_matching_probe(
    toplevel: str, fallbacks: tuple[str, ...], expected: dict[str, str]
) -> None:
    document = FrictionYamlDocument(toplevel=toplevel)

    assert document.effective(fallback_toplevels=fallbacks) == expected


class TestLoadCheckoutPrefs:
    @pytest.fixture()
    def worktree(self, tmp_path: Path) -> Path:
        main = tmp_path / "repo"
        (main / ".git" / "worktrees" / "unrelated").mkdir(parents=True)
        worktree = tmp_path / "wt" / "unrelated"
        worktree.mkdir(parents=True)
        (worktree / ".git").write_text(f"gitdir: {main}/.git/worktrees/unrelated\n")
        return worktree

    def test_linked_worktree_falls_back_to_its_main_checkout(self, worktree: Path) -> None:
        assert load_checkout_prefs(checkout=worktree) == {"tracker": "github", "ide": "none"}

    def test_checkout_entry_wins_without_a_fallback(self, tmp_path: Path) -> None:
        checkout = tmp_path / "feature-x"
        checkout.mkdir()

        assert load_checkout_prefs(checkout=checkout) == {"tracker": "jira", "ide": "none"}

    def test_unmatched_checkout_reads_defaults(self, tmp_path: Path) -> None:
        checkout = tmp_path / "other"
        checkout.mkdir()

        assert load_checkout_prefs(checkout=checkout) == {"tracker": "linear", "ide": "none"}
