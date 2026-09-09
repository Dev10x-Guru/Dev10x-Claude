#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6.0,<7"]
# ///
"""Stop orchestrator (GH-959, GH-1251).

Runs the Stop-event features in-process with per-feature audit records,
consolidating what were separate hook entries into one invocation. Each
feature is isolated — a failure in one does not skip the others.

Features may now express a **verdict** (GH-1251). Previously every
return value was discarded, so no Stop feature could halt a turn; that
is the change `SessionStart` already made for `additionalContext` (see
`.claude/rules/hook-patterns.md` § Consolidation checklist item 5). At
most one envelope is emitted.

**The stdout collision.** `session_goodbye` prints to the user's
terminal while a blocking decision must print JSON on stdout, and the
Stop orchestrator is the first to hold both kinds at once. It is
resolved by ordering rather than interleaving: the goodbye's output is
captured, and replayed only when nothing blocks. A goodbye is a
farewell — printing one while the turn is being continued would say the
session ended when it did not.
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


def _import() -> tuple:
    try:
        from dev10x.hooks import session as s
        from dev10x.hooks.audit_emit import audit_hook
    except ImportError:
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
        from dev10x.hooks import session as s
        from dev10x.hooks.audit_emit import audit_hook
    return s, audit_hook


def _run(*, name: str, fn, audit_hook) -> None:
    """Run a side-effect-only feature, discarding its return value."""
    wrapped = audit_hook(name=name, event="Stop")(fn)
    try:
        wrapped()
    except SystemExit:
        pass
    except Exception:
        traceback.print_exc(file=sys.stderr)


def _capture(*, name: str, fn, audit_hook) -> str:
    """Run a print-based feature, returning its stdout instead of emitting it.

    Partial output from a feature that raised is discarded — replaying
    half a message is worse than replaying none.
    """
    buf = io.StringIO()
    wrapped = audit_hook(name=name, event="Stop")(fn)
    try:
        with contextlib.redirect_stdout(buf):
            wrapped()
    except SystemExit:
        return buf.getvalue()
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return ""
    return buf.getvalue()


def _verdict(*, name: str, fn, audit_hook):
    """Run a verdict-producing feature, returning its verdict or ``None``.

    A feature that raises must not block the turn — an exception here
    means the check did not run, which is not evidence of a skipped
    gate.
    """
    wrapped = audit_hook(name=name, event="Stop")(fn)
    try:
        return wrapped()
    except SystemExit:
        return None
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return None


def main() -> None:
    data = _load_stdin()
    s, audit_hook = _import()

    goodbye = _capture(
        name="session-goodbye",
        fn=lambda: s.session_goodbye(data=data),
        audit_hook=audit_hook,
    )
    _run(name="session-persist", fn=lambda: s.session_persist(data=data), audit_hook=audit_hook)

    verdict = _verdict(
        name="session-stop-verdict",
        fn=lambda: s.build_stop_verdict(data=data),
        audit_hook=audit_hook,
    )

    if verdict is not None and verdict.block:
        print(json.dumps(verdict.to_envelope()))
        return

    if goodbye:
        sys.stdout.write(goodbye)


if __name__ == "__main__":
    main()
