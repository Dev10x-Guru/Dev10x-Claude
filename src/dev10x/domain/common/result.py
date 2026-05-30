from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, cast, runtime_checkable


@runtime_checkable
class ResultProtocol(Protocol):
    """Contract every value crossing the MCP boundary must satisfy.

    Both ``SuccessResult`` and ``ErrorResult`` implement ``to_dict``.
    The ``@server.tool()`` boundary asserts ``isinstance(x,
    ResultProtocol)`` to catch a handler that forgot ``.to_dict()``
    before the wire-encode step (ADR-0009).
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
