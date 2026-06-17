"""CwdResolver — domain-owned seam for effective-CWD resolution.

ADR-0008 Rule #1: ``domain/`` depends only on ``domain/`` and the
standard library. ``GitContext`` must still resolve the caller's
effective working directory — the ContextVar bound by
``subprocess_utils.use_cwd`` after EnterWorktree (GH-979) — but it must
not import the ``subprocess_utils`` infrastructure module to do so
(audit N21, the ``domain → subprocess_utils`` inversion).

This module declares the :class:`CwdResolver` Protocol in the core plus
a single injection seam. The concrete resolver
(``subprocess_utils.effective_cwd``) is wired inward by the infra layer
at import time — infra depending on domain is the allowed direction.

When no resolver is injected, :func:`resolve_cwd` returns ``None`` —
identical to an unbound ContextVar — so any process that never imports
``subprocess_utils`` (and therefore can never have bound a CWD) keeps
inheriting the OS process CWD with no behavior change.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CwdResolver(Protocol):
    """Return the bound effective CWD, or ``None`` when unbound."""

    def __call__(self) -> str | None: ...


_resolver: CwdResolver | None = None


def set_cwd_resolver(resolver: CwdResolver | None) -> None:
    """Inject the effective-CWD resolver (infra wiring / tests).

    Pass ``None`` to reset to the unbound default.
    """
    global _resolver
    _resolver = resolver


def resolve_cwd() -> str | None:
    """Return the injected resolver's result, or ``None`` when unset."""
    return _resolver() if _resolver is not None else None


__all__ = ["CwdResolver", "resolve_cwd", "set_cwd_resolver"]
