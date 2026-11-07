#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["click>=8.0,<9", "msgpack>=1.0,<2", "pyyaml>=6.0,<7"]
# ///
"""PreToolUse hook: review-stamp gate for MCP ship tools (DX019, GH-1830).

Thin shim that delegates to `dev10x hook validate-ship-gate`.
"""

import sys

try:
    from dev10x.commands.hook import validate_ship_gate
except ImportError:
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
    from dev10x.commands.hook import validate_ship_gate

if __name__ == "__main__":
    validate_ship_gate()
