"""Generic Plugin loader (Fowler PoEAA).

Both :mod:`dev10x.validators.registry` and
:mod:`dev10x.skills.doctor.registry` load their extensions the same way:
import a module path late, pull a named attribute (a *marker*) from it,
and keep it only when it satisfies a Protocol. This utility captures that
import → resolve → type-gate mechanic so the two registries stop
reimplementing it independently (audit finding #844).

Two failure postures share one implementation, selected by method:

- :meth:`resolve` / :meth:`collect` — **lenient**: a missing marker or a
  value failing the type gate yields ``None`` (and is dropped by
  ``collect``), so one misconfigured plugin cannot break the whole load.
  The doctor registry uses this.
- :meth:`require` — **strict**: a missing marker or a failed type gate
  raises, surfacing the misconfiguration at load time. The validator
  registry uses this.

A ``transform`` hook adapts the raw attribute before the type gate: the
validator registry resolves a *class* and instantiates it, while the
doctor registry pulls an already-constructed ``STRATEGY`` constant
(identity transform).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from importlib import import_module
from typing import Any

_MISSING = object()


class PluginLoader[T]:
    """Import a module path and resolve a typed marker attribute from it."""

    __slots__ = ("_protocol", "_transform")

    def __init__(
        self,
        *,
        protocol: type[T],
        transform: Callable[[Any], Any] | None = None,
    ) -> None:
        self._protocol = protocol
        self._transform = transform

    def _adapt(self, raw: Any) -> Any:
        return self._transform(raw) if self._transform is not None else raw

    def resolve(self, *, module_path: str, marker: str) -> T | None:
        """Return ``marker`` from ``module_path`` as a ``T``, else ``None``.

        Lenient: an absent marker or a value failing the type gate yields
        ``None`` rather than raising.
        """
        module = import_module(module_path)
        raw = getattr(module, marker, None)
        if raw is None:
            return None
        value = self._adapt(raw)
        return value if isinstance(value, self._protocol) else None

    def require(self, *, module_path: str, marker: str) -> T:
        """Return ``marker`` from ``module_path`` as a ``T``, or raise.

        Strict: raises ``AttributeError`` when the marker is absent and
        ``TypeError`` when the resolved value fails the type gate.
        """
        module = import_module(module_path)
        raw = getattr(module, marker, _MISSING)
        if raw is _MISSING:
            raise AttributeError(f"{module_path!r} has no attribute {marker!r}")
        value = self._adapt(raw)
        if not isinstance(value, self._protocol):
            raise TypeError(f"{module_path}.{marker} is not a {self._protocol.__name__}")
        return value

    def collect(self, sources: Iterable[tuple[str, str]]) -> list[T]:
        """Resolve every ``(module_path, marker)`` source, dropping misses."""
        loaded: list[T] = []
        for module_path, marker in sources:
            item = self.resolve(module_path=module_path, marker=marker)
            if item is not None:
                loaded.append(item)
        return loaded


__all__ = ["PluginLoader"]
