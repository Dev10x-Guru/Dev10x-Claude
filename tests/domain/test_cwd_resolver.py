"""Tests for the domain CwdResolver seam (GH-584, audit N21).

`domain/git_context.py` resolves the effective CWD through this seam
instead of importing `subprocess_utils`, so `domain/` stays free of
outward dependencies (ADR-0008 Rule #1). The infra layer wires the
concrete resolver in at import time.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from dev10x.domain import cwd_resolver


@pytest.fixture(autouse=True)
def _restore_resolver() -> Iterator[None]:
    """Save/restore the module global so tests don't leak into the
    infra-wired default (`subprocess_utils.effective_cwd`)."""
    saved = cwd_resolver._resolver
    try:
        yield
    finally:
        cwd_resolver.set_cwd_resolver(saved)


def test_resolve_returns_none_when_unset() -> None:
    cwd_resolver.set_cwd_resolver(None)
    assert cwd_resolver.resolve_cwd() is None


def test_resolve_uses_injected_resolver() -> None:
    cwd_resolver.set_cwd_resolver(lambda: "/bound/worktree")
    assert cwd_resolver.resolve_cwd() == "/bound/worktree"


def test_reset_clears_injected_resolver() -> None:
    cwd_resolver.set_cwd_resolver(lambda: "/bound/worktree")
    cwd_resolver.set_cwd_resolver(None)
    assert cwd_resolver.resolve_cwd() is None


def test_git_context_does_not_import_subprocess_utils() -> None:
    """Regression guard for the N21 inversion: domain/git_context must
    not import the infra module directly."""
    source = (
        Path(__file__).resolve().parents[2] / "src" / "dev10x" / "domain" / "git_context.py"
    ).read_text()
    assert "from dev10x.subprocess_utils import" not in source
    assert "import dev10x.subprocess_utils" not in source


def test_infra_import_wires_resolver() -> None:
    """Importing subprocess_utils wires effective_cwd into the seam."""
    import dev10x.subprocess_utils as su

    su  # imported for its module-load wiring side effect
    assert cwd_resolver._resolver is su.effective_cwd
