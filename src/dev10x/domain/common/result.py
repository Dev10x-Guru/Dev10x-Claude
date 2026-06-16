from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, cast, runtime_checkable


@runtime_checkable
class ResultProtocol(Protocol):
    """Contract every value crossing the MCP boundary must satisfy.

    Both ``SuccessResult`` and ``ErrorResult`` implement ``to_dict``.
    The ``@server.tool()`` boundary routes its result through
    :func:`to_wire`, which asserts ``isinstance(x, ResultProtocol)``
    to catch a handler that forgot to return a ``Result`` before the
    wire-encode step (ADR-0009).
    """

    def to_dict(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class SuccessResult[T]:
    value: T

    def to_dict(self) -> dict[str, Any]:
        # Contract (ADR-0009): a SuccessResult that reaches the MCP
        # boundary wraps a Mapping, returned unchanged. Internal-only
        # results (e.g. Result[RepositoryRef]) never call to_dict().
        return dict(cast("Mapping[str, Any]", self.value))


@dataclass(frozen=True)
class ErrorResult:
    error: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"error": self.error}
        result.update(self.details)
        return result


type Result[T] = SuccessResult[T] | ErrorResult


def ok[T](value: T) -> SuccessResult[T]:
    return SuccessResult(value=value)


def err(
    error: str,
    **details: Any,
) -> ErrorResult:
    return ErrorResult(error=error, details=details)


def to_wire(result: ResultProtocol) -> dict[str, Any]:
    """Assert the ADR-0009 boundary contract, then wire-encode.

    Every ``@server.tool()`` handler routes its ``Result`` through
    here so a handler that forgot to build a ``Result`` (returning a
    bare value, a ``CompletedProcess``, a raw ``dict``, etc.) fails at
    the boundary with a clear ``TypeError`` instead of at JSON-encode
    time, far from the cause. ``@runtime_checkable`` only verifies the
    ``to_dict`` method is present — the documented scope of the guard.
    """
    if not isinstance(result, ResultProtocol):
        raise TypeError(
            f"MCP boundary expected a Result (got {type(result).__name__}); "
            "a @server.tool() handler likely forgot to return ok()/err()."
        )
    return result.to_dict()
