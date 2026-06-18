from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HookInput:
    tool_name: str
    command: str
    raw: dict[str, Any]
    cwd: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, cwd: str = "") -> HookInput:
        return cls(
            tool_name=data.get("tool_name", ""),
            command=data.get("tool_input", {}).get("command", ""),
            raw=data,
            cwd=cwd,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "command": self.command,
            "raw": self.raw,
            "cwd": self.cwd,
        }


@dataclass(frozen=True)
class HookResult:
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"message": self.message, "decision": "deny"}


@dataclass(frozen=True)
class HookAllow:
    message: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"message": self.message, "decision": "allow"}


@dataclass(frozen=True)
class HookAsk:
    """Prompt the user to approve/deny the tool call in-session (GH-604).

    The sensitivity axis (DX014) emits this for read-only-but-sensitive
    commands: a hard ``deny`` (``HookResult``) would drop the user to a
    manual ``!`` shell, whereas ``ask`` lets them approve the probe in
    the permission dialog. ``reason`` populates Claude Code's
    ``permissionDecisionReason``; ``message`` populates ``systemMessage``.
    """

    message: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"message": self.message, "decision": "ask", "reason": self.reason}


@dataclass(frozen=True)
class HookRetry:
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"message": self.message, "decision": "retry"}
