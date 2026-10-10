"""HookEventName — typed Claude Code hook event identifiers.

The event names (``"PreToolUse"``, ``"SessionStart"``, …) were raw
string literals scattered across the ``@audit_hook`` decorator, the
``hookSpecificOutput`` envelopes, and assorted call sites (audit
finding C8 — 2026-05-18). A typo silently produced a mislabeled audit
record or an envelope Claude Code ignored.

``HookEventName`` is a :class:`enum.StrEnum`, so each member *is* a
``str``: it serialises into JSON envelopes and audit records unchanged
while giving callers a single authoritative spelling to reference.
"""

from __future__ import annotations

from enum import StrEnum


class HookEventName(StrEnum):
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    PERMISSION_DENIED = "PermissionDenied"
    SESSION_START = "SessionStart"
    STOP = "Stop"
    PRE_COMPACT = "PreCompact"
