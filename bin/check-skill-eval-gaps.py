#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Scan skills/ for gated skills shipping zero eval assertions (GH-835).

Usage:
    bin/check-skill-eval-gaps.py [--all] [SKILL_DIR ...]

Exits with status 1 if any gated skill has missing or empty eval coverage.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from dev10x.teach.skills.audit.eval_gaps_cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(argv=sys.argv[1:], repo_root=REPO_ROOT))
