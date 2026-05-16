#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""PostToolUse hook for Skill invocations — direct shebang replacement
for `dev10x hook skill metrics` (GH-959).

Wrapped with @audit_hook so body-phase timing lands in the JSONL log.
"""

import sys

try:
    from dev10x.hooks.audit_emit import audit_hook
    from dev10x.hooks.skill import skill_metrics
except ImportError:
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
    from dev10x.hooks.audit_emit import audit_hook
    from dev10x.hooks.skill import skill_metrics

if __name__ == "__main__":
    audit_hook(name="skill-metrics", event="PostToolUse")(skill_metrics)()
