"""Milestone prefix registry parsing and the creation-time check (GH-1690)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from dev10x.domain.milestone_prefixes import (
    REGISTRY_RELPATH,
    parse_registered_prefixes,
    title_prefix,
    unregistered_prefix_error,
)

from dev10x.core.github import _gateway

_REPO_ROOT = Path(__file__).parents[2]

_DOC = """# Milestone Naming

| `NOTE` | a table outside the registry | ignored |

## Registered Initiative Prefixes

| Prefix | Initiative | Status |
|--------|-----------|--------|
| `AUD` | Audit | closed |
| `DX` | Developer experience | active |

## Lifecycle Rule

| `LATER` | after the registry | ignored |
"""


def test_parses_only_the_registry_table() -> None:
    assert parse_registered_prefixes(text=_DOC) == frozenset({"AUD", "DX"})


def test_the_repository_registry_parses() -> None:
    text = (_REPO_ROOT / REGISTRY_RELPATH).read_text(encoding="utf-8")

    assert {"ARCH", "DX", "PERM"} <= parse_registered_prefixes(text=text)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("DX: Green CI", "DX"),
        ("ARCH-M6: Make the quality gates real", "ARCH"),
        ("dx: lowercase", None),
        ("TOOLONGX: seven letters", None),
        ("DX:missing space", None),
        ("Plain outcome", None),
    ],
)
def test_title_prefix(title: str, expected: str | None) -> None:
    assert title_prefix(title=title) == expected


def test_a_registered_prefix_passes() -> None:
    assert unregistered_prefix_error(title="DX: Green CI", registered=frozenset({"DX"})) is None


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("NEW: Something", "| `NEW` | <initiative> | active |"),
        ("Plain outcome", "does not start with an initiative prefix"),
    ],
    ids=["unregistered-names-the-row", "no-prefix"],
)
def test_a_refused_title_says_how_to_fix_it(title: str, expected: str) -> None:
    error = unregistered_prefix_error(title=title, registered=frozenset({"DX"}))

    assert expected in str(error)


class TestRegistryLoader:
    def test_reads_the_checkout_registry(self, tmp_path: Path) -> None:
        registry = tmp_path / REGISTRY_RELPATH
        registry.parent.mkdir(parents=True)
        registry.write_text(_DOC, encoding="utf-8")

        with patch.object(_gateway, "GitContext") as git_context:
            git_context.return_value.toplevel = str(tmp_path)
            loaded = _gateway._milestone_prefix_registry()

        assert loaded == frozenset({"AUD", "DX"})

    def test_a_checkout_without_a_registry_is_not_guarded(self, tmp_path: Path) -> None:
        with patch.object(_gateway, "GitContext") as git_context:
            git_context.return_value.toplevel = str(tmp_path)
            loaded = _gateway._milestone_prefix_registry()

        assert loaded is None

    def test_outside_a_repository_is_not_guarded(self) -> None:
        with patch.object(_gateway, "GitContext") as git_context:
            git_context.return_value.toplevel = None
            loaded = _gateway._milestone_prefix_registry()

        assert loaded is None
