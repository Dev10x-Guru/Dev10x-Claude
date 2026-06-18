"""Typed process-level singleton holder.

**Not a Registry.** Per audit finding A3 the name ``Registry`` is
reserved for static lookup tables (see ``dev10x.platform.registry`` and
``PlatformRepository``'s docstring). This type owns a single *mutable*
process-level slot — one swappable instance — so modules stop
reimplementing the ``global _x`` + ``get_x()`` + ``set_x()`` trio
independently (the DRY-at-the-architectural-level concern behind
GH-522).

Usage: construct one module-level holder seeded with a default (or
empty), then expose thin ``get_*`` / ``set_*`` accessors that delegate
to it::

    _holder: SingletonHolder[SessionStore] = SingletonHolder(default=SessionStore())

    def get_store() -> SessionStore:
        store = _holder.get()
        if store is None:
            store = SessionStore()
            _holder.set(store)
        return store

Tests swap the instance via the holder (or the public ``set_*``
accessor) instead of monkey-patching a bare module global.
"""

from __future__ import annotations


class SingletonHolder[T]:
    """Holds one swappable process-level instance behind a typed slot."""

    __slots__ = ("_value",)

    def __init__(self, *, default: T | None = None) -> None:
        self._value: T | None = default

    def get(self) -> T | None:
        """Return the held instance, or ``None`` when unset."""
        return self._value

    def set(self, value: T | None) -> None:
        """Replace the held instance; pass ``None`` to clear the slot."""
        self._value = value

    def reset(self) -> None:
        """Clear the slot back to ``None``."""
        self._value = None
