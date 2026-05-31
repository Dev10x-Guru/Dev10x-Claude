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

    ``mode`` selects the calling convention:
      - ``"capture"`` — wrap with ``audit_hook`` and capture stdout
        (legacy print-based features). ``pass_data`` forwards stdin.
      - ``"build"``  — call directly and use the returned string.
    ``emits_context`` is False for side-effect-only features (tmpdir).
    """

    name: str
    fn: Callable[..., Any]
    mode: str
    pass_data: bool = False
    emits_context: bool = True


def _run_session_feature(*, feature: SessionFeature, data: dict, audit_hook) -> str:
    """Run one feature, returning the context string to append (or "")."""
    if feature.mode == "build":
        try:
            return feature.fn() or ""
        except Exception:
            traceback.print_exc(file=sys.stderr)
            return ""

    fn = (lambda: feature.fn(data=data)) if feature.pass_data else feature.fn
    out = _run_feature(name=feature.name, fn=fn, audit_hook=audit_hook)
    return out.strip() if feature.emits_context else ""


def main() -> None:
    data = _load_stdin()
    s, audit_hook = _import_session_modules()

    # Order matters for readability of the merged additionalContext.
    features = [
        SessionFeature(name="session-git-aliases", fn=s.session_git_aliases, mode="capture"),
        SessionFeature(
            name="session-tmpdir",
            fn=s.session_tmpdir,
            mode="capture",
            pass_data=True,
            emits_context=False,
        ),
        SessionFeature(name="session-guidance", fn=s.build_guidance_context, mode="build"),
        SessionFeature(
            name="session-autonomy",
            fn=s.build_autonomy_reassurance_context,
            mode="build",
        ),
        SessionFeature(
            name="session-install-check",
            fn=s.build_install_check_context,
            mode="build",
        ),
        SessionFeature(
            name="session-migrate-permissions",
            fn=s.session_migrate_permissions,
            mode="capture",
        ),
        SessionFeature(name="session-reload", fn=s.build_reload_context, mode="build"),
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
