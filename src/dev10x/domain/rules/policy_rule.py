"""PolicyRule — the Policy Rule archetype contract (ADR-0007).

A Policy Rule is a small immutable object that computes one named
decision via ``apply()`` and performs no I/O — persistence is delegated
to the Document layer (``domain/documents/``). This Protocol formalises
the contract the ``*Rule`` policy classes previously satisfied only by
convention.

The codebase has three deliberately distinct "rule" archetypes
(ADR-0007); this Protocol formalises only the Policy Rule tier:

- **Matching Rule** (``domain.rules.validation_rule.Rule``) — declarative
  data + ``matches_*`` predicates, no ``apply()``.
- **Policy Rule** (this Protocol) — one named decision via ``apply()``.
- **Validator** (``validators.base.Validator``) — ``should_run()`` +
  ``validate()`` chain element with its own registry lifecycle.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PolicyRule[T](Protocol):
    """One named decision computed by ``apply()`` with no side effects."""

    def apply(self) -> T: ...


__all__ = ["PolicyRule"]
