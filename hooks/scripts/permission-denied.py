#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["click>=8.0,<9", "msgpack>=1.0,<2", "pyyaml>=6.0,<7"]
# ///
"""PermissionDenied hook: provide corrective guidance after auto-mode denial.

Thin shim that delegates to `dev10x hook permission-denied`.
"""

import sys

try:
    from dev10x.commands.hook import permission_denied
except ImportError:
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
    from dev10x.commands.hook import permission_denied

if __name__ == "__main__":
    permission_denied()
