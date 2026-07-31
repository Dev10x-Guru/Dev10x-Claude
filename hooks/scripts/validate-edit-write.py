#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["msgpack>=1.0,<2", "pyyaml>=6.0,<7"]
# ///
"""PreToolUse hook: thin shim delegating to dev10x.hooks.edit_validator.

Kept for backward compatibility with plugin.json hook config.
All logic lives in src/dev10x/hooks/edit_validator.py.
"""

import json
import sys

try:
    from dev10x.hooks.edit_validator import validate_edit_write
except ImportError:
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
    from dev10x.hooks.edit_validator import validate_edit_write

try:
    data = json.load(sys.stdin)
except (json.JSONDecodeError, EOFError):
    sys.exit(0)

validate_edit_write(data=data)
