#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Thin shim — delegates to dev10x.skills.git_fixup.find_fixup_target."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from dev10x.skills.git_fixup.find_fixup_target import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
