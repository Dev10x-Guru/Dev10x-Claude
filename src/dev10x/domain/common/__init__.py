"""Value Objects shared across the domain core (Fowler PoEAA).

Most modules in this package define a frozen dataclass that is a
textbook **Value Object** — identity by value, immutable, no
lifecycle. ``SkillName``, ``BranchName``, ``TicketId``,
``RepositoryRef``, and ``AllowRule`` are the canonical examples;
their sibling single-value wrappers follow the same shape. (The
``policy`` module additionally hosts ``StrEnum`` effect/tier types,
and ``result`` holds the shared ``Result`` contract — neither is a
Value Object.)

New Value Objects added here should preserve the convention:
``@dataclass(frozen=True)`` with equality by value and no mutable
state. Document deviations explicitly rather than introducing a
mutable variant by accident.

This package re-exports nothing — import the concrete type from its
sibling module (e.g. ``from dev10x.domain.common.branch_name import
BranchName``).
"""
