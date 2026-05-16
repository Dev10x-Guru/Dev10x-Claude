from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Any, NoReturn


@dataclass(frozen=True)
class HookInput:
    tool_name: str
    command: str
    raw: dict[str, Any]
    cwd: str = ""

    @classmethod
    def from_stdin(cls) -> HookInput:
        try:
            data = json.load(sys.stdin)
        except (json.JSONDecodeError, EOFError):
            data = {}
        return cls(
            tool_name=data.get("tool_name", ""),
            command=data.get("tool_input", {}).get("command", ""),
            raw=data,
            cwd=os.getcwd(),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HookInput:
        return cls(
            tool_name=data.get("tool_name", ""),
            command=data.get("tool_input", {}).get("command", ""),
            raw=data,
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

    def emit(self) -> NoReturn:
        result = {
            "hookSpecificOutput": {"permissionDecision": "deny"},
            "systemMessage": self.message,
        }
        print(json.dumps(result), file=sys.stderr)
        sys.exit(2)

    def to_dict(self) -> dict[str, str]:
        return {"message": self.message, "decision": "deny"}


@dataclass(frozen=True)
class HookAllow:
    message: str = ""

    def emit(self) -> NoReturn:
        result: dict[str, Any] = {
            "hookSpecificOutput": {"permissionDecision": "allow"},
        }
        if self.message:
            result["systemMessage"] = self.message
        print(json.dumps(result), file=sys.stderr)
        sys.exit(0)

    def to_dict(self) -> dict[str, str]:
        return {"message": self.message, "decision": "allow"}


@dataclass(frozen=True)
class HookRetry:
    message: str

    def emit(self) -> NoReturn:
        result: dict[str, Any] = {
            "hookSpecificOutput": {
                "hookEventName": "PermissionDenied",
                "retry": True,
            },
        }
        if self.message:
            result["systemMessage"] = self.message
        print(json.dumps(result), file=sys.stderr)
        sys.exit(0)

    def to_dict(self) -> dict[str, str]:
        return {"message": self.message, "decision": "retry"}
