#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["click>=8.0,<9", "msgpack>=1.0,<2", "pyyaml>=6.0,<7"]
# ///
"""PreToolUse hook: unified Bash command validator.

Thin shim that delegates to `dev10x hook validate-bash`.
Kept for backward compatibility with plugin.json hook config.
"""

import sys

try:
    from dev10x.commands.hook import validate_bash
except ImportError:
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
    from dev10x.commands.hook import validate_bash

if __name__ == "__main__":
    validate_bash()
