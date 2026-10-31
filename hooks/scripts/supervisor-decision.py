#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6.0,<7"]
# ///
"""PreToolUse hook for AskUserQuestion — hands the open questions to the
local supervisor page (GH-1692). Silent and non-blocking by design.
"""

import sys

try:
    from dev10x.hooks.audit_emit import audit_hook

    from dev10x.comm.hooks.supervisor_decision import supervisor_decision
except ImportError:
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
    from dev10x.hooks.audit_emit import audit_hook

    from dev10x.comm.hooks.supervisor_decision import supervisor_decision

if __name__ == "__main__":
    audit_hook(name="supervisor-decision", event="PreToolUse")(supervisor_decision)()
