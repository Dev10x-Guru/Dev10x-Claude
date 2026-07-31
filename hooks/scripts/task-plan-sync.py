#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6.0,<7"]
# ///
"""PostToolUse hook: thin shim delegating to dev10x.hooks.task_plan_sync.

Kept for backward compatibility with plugin.json hook config.
All logic lives in src/dev10x/hooks/task_plan_sync.py.
"""

import sys

try:
    from dev10x.hooks.task_plan_sync import (
        cmd_archive,
        cmd_hook,
        cmd_json_summary,
        cmd_set_context,
    )
except ImportError:
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
    from dev10x.hooks.task_plan_sync import (
        cmd_archive,
        cmd_hook,
        cmd_json_summary,
        cmd_set_context,
    )

if "--json-summary" in sys.argv:
    cmd_json_summary()
elif "--set-context" in sys.argv:
    idx = sys.argv.index("--set-context")
    cmd_set_context(args=sys.argv[idx + 1 :])
elif "--archive" in sys.argv:
    cmd_archive()
else:
    cmd_hook()
