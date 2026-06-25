#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""SessionStart orchestrator (GH-959).

Runs all SessionStart features in-process with per-feature audit
records, consolidating what were previously 5 separate hook entries
(git-aliases, tmpdir, guidance, migrate-permissions, reload) into a
single invocation. Each feature is isolated — a failure in one does
not skip the others. The orchestrator emits a single merged
additionalContext JSON to stdout.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import traceback
from collections.abc import Callable
from typing import Any, NamedTuple


def _load_stdin() -> dict:
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        return {}


def _import_session_modules() -> tuple:
    try:
        from dev10x.hooks import session as s
        from dev10x.hooks.audit_emit import audit_hook
    except ImportError:
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
        from dev10x.hooks import session as s
        from dev10x.hooks.audit_emit import audit_hook

    return s, audit_hook


def _run_feature(*, name: str, fn, audit_hook) -> str:
    """Run one feature function, capturing stdout. Returns captured text.

    Failures are logged to stderr but do not propagate. Partial stdout
    captured before an exception is discarded — appending a truncated
    JSON envelope to ``context_parts`` would corrupt the merged
    ``hookSpecificOutput`` payload sent back to Claude Code.
    """
    buf = io.StringIO()
    wrapped = audit_hook(name=name, event="SessionStart")(fn)
    try:
        with contextlib.redirect_stdout(buf):
            wrapped()
    except SystemExit:
        return buf.getvalue()
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return ""
    return buf.getvalue()


def _extract_additional_context(*, output: str) -> str:
    """Pull additionalContext from a printed hookSpecificOutput JSON blob.

    Features like session_reload and session_guidance print:
        {"hookSpecificOutput":{"hookEventName":"SessionStart",
         "additionalContext":"..."}}
    When consolidating, we strip the outer envelope and merge the
    inner strings. If parsing fails, treat the whole string as plain
    additionalContext (preserves legacy stdout prints).
    """
    stripped = output.strip()
    if not stripped:
        return ""
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped
    ctx = obj.get("hookSpecificOutput", {}).get("additionalContext", "")
    return ctx or stripped


class SessionFeature(NamedTuple):
    """One SessionStart feature and how to obtain its context string.

    A ``NamedTuple`` (not a dataclass) so this standalone uv-script stays
    importable under ``importlib.exec_module`` with a synthetic module
    name — ``@dataclass`` + ``from __future__ import annotations`` does a
    ``sys.modules`` lookup that fails outside a registered module.

    ``run`` encapsulates the calling convention for this feature — it
    receives ``(data, audit_hook)`` and returns the context string (or
    ``""``). Use :func:`capture_feature` or :func:`build_feature` to
    construct a ``SessionFeature`` with the correct ``run`` callable
    rather than building it by hand.
    """

    name: str
    fn: Callable[..., Any]
    run: Callable[..., str]


def capture_feature(
    *,
    name: str,
    fn: Callable[..., Any],
    pass_data: bool = False,
    emits_context: bool = True,
) -> SessionFeature:
    """Return a ``SessionFeature`` that wraps ``fn`` with ``audit_hook`` and captures stdout.

    Used for legacy print-based features. When ``pass_data`` is True, the
    stdin ``data`` dict is forwarded to ``fn``. When ``emits_context`` is
    False the captured stdout is discarded (side-effect-only features such
    as tmpdir setup).
    """

    def _run(data: dict, audit_hook) -> str:
        inner_fn = (lambda: fn(data=data)) if pass_data else fn
        out = _run_feature(name=name, fn=inner_fn, audit_hook=audit_hook)
        return out.strip() if emits_context else ""

    return SessionFeature(name=name, fn=fn, run=_run)


def build_feature(*, name: str, fn: Callable[..., Any]) -> SessionFeature:
    """Return a ``SessionFeature`` that calls ``fn`` directly and uses the returned string.

    Used for features that return their context string rather than printing it.
    """

    def _run(data: dict, audit_hook) -> str:  # noqa: ARG001
        try:
            return fn() or ""
        except Exception:
            traceback.print_exc(file=sys.stderr)
            return ""

    return SessionFeature(name=name, fn=fn, run=_run)


def _run_session_feature(*, feature: SessionFeature, data: dict, audit_hook) -> str:
    """Run one feature, returning the context string to append (or "")."""
    return feature.run(data, audit_hook)


def main() -> None:
    data = _load_stdin()
    s, audit_hook = _import_session_modules()

    # Order matters for readability of the merged additionalContext.
    features = [
        capture_feature(name="session-git-aliases", fn=s.session_git_aliases),
        capture_feature(
            name="session-tmpdir",
            fn=s.session_tmpdir,
            pass_data=True,
            emits_context=False,
        ),
        build_feature(name="session-guidance", fn=s.build_guidance_context),
        build_feature(name="session-autonomy", fn=s.build_autonomy_reassurance_context),
        build_feature(name="session-auto-plan", fn=s.build_auto_plan_guidance_context),
        build_feature(name="session-install-check", fn=s.build_install_check_context),
        build_feature(name="session-hook-version-drift", fn=s.build_hook_version_drift_context),
        capture_feature(name="session-migrate-permissions", fn=s.session_migrate_permissions),
        build_feature(name="session-reload", fn=s.build_reload_context),
    ]

    context_parts: list[str] = []
    for feature in features:
        ctx = _run_session_feature(feature=feature, data=data, audit_hook=audit_hook)
        if ctx:
            context_parts.append(ctx)

    if not context_parts:
        return

    merged = "\n\n".join(context_parts)
    envelope = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": merged,
        }
    }
    print(json.dumps(envelope))


if __name__ == "__main__":
    main()
