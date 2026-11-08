#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["click>=8.0,<9", "msgpack>=1.0,<2", "pyyaml>=6.0,<7"]
# ///
"""PreToolUse hook: Agent briefs name the skill owning their work (DX020, GH-1835).

Thin shim that delegates to `dev10x hook validate-agent-brief`.
"""

import sys

try:
    from dev10x.commands.hook import validate_agent_brief
except ImportError:
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
    from dev10x.commands.hook import validate_agent_brief

if __name__ == "__main__":
    validate_agent_brief()
