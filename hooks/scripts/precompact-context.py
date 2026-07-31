#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6.0,<7"]
# ///
"""PreCompact hook: thin shim delegating to dev10x.hooks.session.

All logic lives in src/dev10x/hooks/session.py.
"""

import sys

try:
    from dev10x.hooks.session import context_compact
except ImportError:
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
    from dev10x.hooks.session import context_compact

if __name__ == "__main__":
    context_compact()
