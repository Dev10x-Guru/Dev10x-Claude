"""Hook transport adapter — owns stdin reads and the wire response.

GH-511: the Claude Code hook envelope (``hookSpecificOutput`` +
``sys.exit``) and stdin parsing are process-boundary concerns. They
live here in the ``dev10x.hooks`` adapter layer rather than on the
``dev10x.domain.events`` value objects, per
``.claude/rules/script-domain-boundaries.md`` (GH-246 H3/H7): domain
objects keep their data shape and ``to_dict()``; this thin adapter
translates a domain decision into the wire response and owns the
exit code.
"""

from __future__ import annotations

import json
import os
import sys
from typing import NoReturn

from dev10x.domain.events.hook_event import HookEventName
from dev10x.domain.events.hook_input import HookAllow, HookAsk, HookInput, HookResult, HookRetry
from dev10x.subprocess_utils import effective_cwd


def read_hook_input() -> HookInput:
    """Parse the hook JSON envelope from stdin into a ``HookInput``.

    Resolves the effective working directory (bound worktree wins,
    process CWD is the fallback) so downstream git/gh subprocesses
    target the caller's root — the transport-layer counterpart to the
    GH-979 CWD discipline.
    """
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        data = {}
    return HookInput.from_dict(data=data, cwd=effective_cwd() or os.getcwd())


def emit(result: HookResult | HookAllow | HookAsk | HookRetry) -> NoReturn:
    """Write the Claude Code hook envelope for ``result`` and exit.

    ``HookResult`` denies the tool call (exit 2); ``HookAllow``,
    ``HookAsk``, and ``HookRetry`` all exit 0 with their
    decision-specific envelope. ``HookAsk`` returns
    ``permissionDecision: "ask"`` so Claude Code shows the in-session
    approval dialog (GH-604) — exit 0, not 2, since the decision is
    carried in the JSON rather than the exit code.
    """
    if isinstance(result, HookResult):
        payload: dict[str, object] = {
            "hookSpecificOutput": {"permissionDecision": "deny"},
            "systemMessage": result.message,
        }
        print(json.dumps(payload), file=sys.stderr)
        sys.exit(2)

    if isinstance(result, HookAllow):
        payload = {"hookSpecificOutput": {"permissionDecision": "allow"}}
        if result.message:
            payload["systemMessage"] = result.message
        print(json.dumps(payload), file=sys.stderr)
        sys.exit(0)

    if isinstance(result, HookAsk):
        payload = {
            "hookSpecificOutput": {
                "hookEventName": HookEventName.PRE_TOOL_USE,
                "permissionDecision": "ask",
                "permissionDecisionReason": result.reason or result.message,
            },
        }
        if result.message:
            payload["systemMessage"] = result.message
        print(json.dumps(payload), file=sys.stderr)
        sys.exit(0)

    payload = {
        "hookSpecificOutput": {
            "hookEventName": HookEventName.PERMISSION_DENIED,
            "retry": True,
        },
    }
    if result.message:
        payload["systemMessage"] = result.message
    print(json.dumps(payload), file=sys.stderr)
    sys.exit(0)
