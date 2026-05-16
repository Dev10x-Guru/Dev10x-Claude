from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SuccessResult[T]:
    value: T

    def to_dict(self) -> dict[str, Any]:
        if isinstance(self.value, dict):
            return self.value
        return {"value": self.value}


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
