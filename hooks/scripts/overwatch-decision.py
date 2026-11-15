#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6.0,<7"]
# ///
"""PreToolUse hook for AskUserQuestion — hands the open questions to the
local Overwatch page (GH-1692). Silent and non-blocking by design.
"""

import sys

try:
    from dev10x.comm.hooks.overwatch_decision import overwatch_decision
    from dev10x.core.hooks.audit_emit import audit_hook
except ImportError:
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
    from dev10x.comm.hooks.overwatch_decision import overwatch_decision
    from dev10x.core.hooks.audit_emit import audit_hook

if __name__ == "__main__":
    audit_hook(name="overwatch-decision", event="PreToolUse")(overwatch_decision)()
