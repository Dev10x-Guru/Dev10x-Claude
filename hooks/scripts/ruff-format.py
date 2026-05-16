#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""PostToolUse hook for Edit|Write — direct shebang replacement for
`dev10x hook ruff-format` (GH-959).

Wrapped with @audit_hook so body-phase timing lands in the JSONL log.
"""

import sys

try:
    from dev10x.hooks.audit_emit import audit_hook
    from dev10x.hooks.skill import ruff_format
except ImportError:
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
    from dev10x.hooks.audit_emit import audit_hook
    from dev10x.hooks.skill import ruff_format

if __name__ == "__main__":
    audit_hook(name="ruff-format", event="PostToolUse")(ruff_format)()
