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


def main() -> None:
    data = _load_stdin()
    s, audit_hook = _import_session_modules()

    # Features that produce additionalContext (order matters for readability).
    context_parts: list[str] = []

    out = _run_feature(
        name="session-git-aliases", fn=s.session_git_aliases, audit_hook=audit_hook
    )
    if out.strip():
        context_parts.append(out.strip())

    _run_feature(
        name="session-tmpdir",
        fn=lambda: s.session_tmpdir(data=data),
        audit_hook=audit_hook,
    )

    guidance = s.build_guidance_context()
    if guidance:
        context_parts.append(guidance)

    reassurance = s.build_autonomy_reassurance_context()
    if reassurance:
        context_parts.append(reassurance)

    install_check = s.build_install_check_context()
    if install_check:
        context_parts.append(install_check)

    out = _run_feature(
        name="session-migrate-permissions",
        fn=s.session_migrate_permissions,
        audit_hook=audit_hook,
    )
    if out.strip():
        context_parts.append(out.strip())

    reload_ctx = s.build_reload_context()
    if reload_ctx:
        context_parts.append(reload_ctx)

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
