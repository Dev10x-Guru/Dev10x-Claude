#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Thin shim — delegates to dev10x.core.fixes_trailer (GH-1873)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dev10x.core.fixes_trailer import *  # noqa: E402, F401, F403
from dev10x.core.fixes_trailer import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
