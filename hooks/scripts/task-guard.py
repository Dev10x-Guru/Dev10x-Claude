#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""PreToolUse hook: thin shim delegating to dev10x.hooks.task_guard.

Enforces the empty-task-list invariant (GH-681 / GH-149). All logic
lives in src/dev10x/hooks/task_guard.py.
"""

import sys

try:
    from dev10x.hooks.task_guard import cmd_hook
except ImportError:
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
    from dev10x.hooks.task_guard import cmd_hook

cmd_hook()
