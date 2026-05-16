#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Thin CLI shim: record a wrap-phase audit entry.

Invoked by hooks/scripts/audit-wrap after a child process exits.
All logic lives in src/dev10x/hooks/audit_emit.py so the wrap record
format stays consistent with decorator-written body records.

Usage: audit-record.py <hook> <span_id> <total_ms> <exit_code> [argv...]
"""

import sys

try:
    from dev10x.hooks.audit_emit import cli_wrap_record
except ImportError:
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
    from dev10x.hooks.audit_emit import cli_wrap_record

if __name__ == "__main__":
    cli_wrap_record()
