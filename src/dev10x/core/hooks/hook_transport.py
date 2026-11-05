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
import logging
import os
import sys
from dataclasses import replace
from typing import NoReturn

from dev10x.domain.events.hook_event import HookEventName
from dev10x.domain.events.hook_input import (
    HookAllow,
    HookAsk,
    HookHint,
    HookInput,
    HookResult,
    HookRetry,
)
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


def _record_attribution(*, rule_id: str, reason: str) -> None:
    """Hand a deny/ask decision to the audit layer before exiting (GH-1095).

    Never let telemetry break the hook: a failure here would turn a
    clean deny into a crash, so the catch stays broad and the audit
    record falls back to its pre-GH-1095 shape.

    It is logged rather than silently dropped (GH-494's "always
    surface" precedent): a future signature change in
    ``set_decision_attribution`` would otherwise fail here invisibly
    and defeat attribution with no trail.
    """
    if not rule_id and not reason:
        return
    try:
        from dev10x.hooks.audit_emit import set_decision_attribution

        set_decision_attribution(rule_id=rule_id, reason=reason)
    except Exception:  # pragma: no cover - telemetry must never block a hook
        logging.getLogger(__name__).warning(
            "attribution recording failed; audit record falls back to its pre-GH-1095 shape",
            exc_info=True,
        )


def select_result(
    results: list[HookResult | HookAllow | HookAsk | HookHint],
) -> HookResult | HookAllow | HookAsk | HookHint | None:
    """The one result the hook should emit for a validator chain run.

    ``emit`` exits, so the first result emitted is the only one that
    counts. Precedence is deny > ask > allow, wherever each sits in the
    chain (GH-1795): an allow can now skip the prompt, so stopping at the
    first one would let it shadow a later validator's deny. A hint decides
    nothing and never stands in front of a decision (GH-1725).

    Advisory allows (``decides`` false) count as hints. Every hint's
    message rides along as context on a deciding allow, or is merged into
    one context block when nothing decided.
    """
    for kind in (HookResult, HookAsk):
        decision = next((result for result in results if isinstance(result, kind)), None)
        if decision is not None:
            return decision

    advice = [
        result
        for result in results
        if isinstance(result, HookHint) or (isinstance(result, HookAllow) and not result.decides)
    ]
    context = "\n\n".join(result.message for result in advice if result.message)
    allow = next(
        (result for result in results if isinstance(result, HookAllow) and result.decides),
        None,
    )
    if allow is not None:
        merged = "\n\n".join(message for message in (allow.message, context) if message)
        return replace(allow, message=merged)
    if not context:
        return None
    return HookHint(message=context, rule_id=next(r.rule_id for r in advice if r.message))


def _emit_context(*, message: str) -> NoReturn:
    payload = {
        "hookSpecificOutput": {
            "hookEventName": HookEventName.PRE_TOOL_USE,
            "additionalContext": message,
        },
    }
    print(json.dumps(payload))
    sys.exit(0)


def emit(result: HookResult | HookAllow | HookAsk | HookHint | HookRetry) -> NoReturn:
    """Write the Claude Code hook envelope for ``result`` and exit.

    Stream contract (GH-1775): Claude Code parses an exit-0 hook's JSON
    from stdout only and never reads its stderr, so every exit-0 envelope
    goes to stdout. A deny exits 2, where stderr is what Claude sees.

    ``HookResult`` denies the tool call (exit 2). ``HookAsk`` returns
    ``permissionDecision: "ask"`` so Claude Code shows the in-session
    approval dialog (GH-604). ``HookRetry`` lets a PermissionDenied
    hook tell the model it may retry. A deciding ``HookAllow`` returns
    ``permissionDecision: "allow"`` and skips the prompt (GH-1795); its
    message is the decision reason and reaches the agent as context. An
    advisory allow emits context only, like a hint.
    """
    if isinstance(result, HookResult):
        _record_attribution(rule_id=result.rule_id, reason=result.message)
        payload: dict[str, object] = {
            "hookSpecificOutput": {"permissionDecision": "deny"},
            "systemMessage": result.message,
        }
        print(json.dumps(payload), file=sys.stderr)
        sys.exit(2)

    if isinstance(result, HookAllow):
        if not result.decides:
            if result.message:
                _emit_context(message=result.message)
            sys.exit(0)
        _record_attribution(rule_id=result.rule_id, reason=result.message)
        allow_output: dict[str, str] = {
            "hookEventName": HookEventName.PRE_TOOL_USE,
            "permissionDecision": "allow",
        }
        if result.message:
            allow_output["permissionDecisionReason"] = result.message
            allow_output["additionalContext"] = result.message
        print(json.dumps({"hookSpecificOutput": allow_output}))
        sys.exit(0)

    if isinstance(result, HookHint):
        # No permissionDecision — the call proceeds as it would have.
        _record_attribution(rule_id=result.rule_id, reason=result.message)
        _emit_context(message=result.message)

    if isinstance(result, HookAsk):
        _record_attribution(rule_id=result.rule_id, reason=result.reason or result.message)
        payload = {
            "hookSpecificOutput": {
                "hookEventName": HookEventName.PRE_TOOL_USE,
                "permissionDecision": "ask",
                "permissionDecisionReason": result.reason or result.message,
            },
        }
        if result.message:
            payload["systemMessage"] = result.message
        print(json.dumps(payload))
        sys.exit(0)

    payload = {
        "hookSpecificOutput": {
            "hookEventName": HookEventName.PERMISSION_DENIED,
            "retry": True,
        },
    }
    if result.message:
        payload["systemMessage"] = result.message
    print(json.dumps(payload))
    sys.exit(0)
