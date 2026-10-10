"""Hook telemetry enums — phase and outcome of an audited hook record.

Replaces string literals scattered across ``hooks/audit.py`` (``"body"`` /
``"wrap"`` / ``"ok"`` / ``"block"`` / ``"error"`` / ``"unknown"``) with
type-safe StrEnums. Values preserve the existing JSONL on-disk
representation so the audit log stays backwards-compatible.
"""

from __future__ import annotations

from enum import StrEnum


class HookPhase(StrEnum):
    """Which side of the hook lifecycle a record describes."""

    BODY = "body"
    WRAP = "wrap"


class HookOutcome(StrEnum):
    """Exit-status classification recorded for each hook invocation."""

    OK = "ok"
    BLOCK = "block"
    ERROR = "error"
    UNKNOWN = "unknown"

    @classmethod
    def from_exit_code(cls, exit_code: int) -> HookOutcome:
        """Map a Claude-Code hook exit code to its outcome bucket.

        - 0 → OK
        - 2 → BLOCK (PreToolUse deny / informational block)
        - 1 → ERROR
        - anything else → UNKNOWN
        """
        if exit_code == 0:
            return cls.OK
        if exit_code == 2:
            return cls.BLOCK
        if exit_code == 1:
            return cls.ERROR
        return cls.UNKNOWN


__all__ = ["HookPhase", "HookOutcome"]
