#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Stop orchestrator (GH-959).

Runs the two Stop-event features (goodbye, persist) in-process with
per-feature audit records, consolidating two separate hook entries
into one invocation. Each feature is isolated — a failure in one
does not skip the others.
"""

from __future__ import annotations

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
    wrapped = audit_hook(name=name, event="Stop")(fn)
    try:
        wrapped()
    except SystemExit:
        pass
    except Exception:
        traceback.print_exc(file=sys.stderr)


def main() -> None:
    data = _load_stdin()
    s, audit_hook = _import()

    _run(name="session-goodbye", fn=lambda: s.session_goodbye(data=data), audit_hook=audit_hook)
    _run(name="session-persist", fn=lambda: s.session_persist(data=data), audit_hook=audit_hook)


if __name__ == "__main__":
    main()
