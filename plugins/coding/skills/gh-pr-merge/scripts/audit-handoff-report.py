#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Thin shim — delegates to dev10x.coding.skills.merge.handoff_audit."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "git" / "lib"))

from core_src import add_core_src  # noqa: E402

add_core_src(script=Path(__file__))

from dev10x.coding.skills.merge.handoff_audit import *  # noqa: E402, F401, F403
from dev10x.coding.skills.merge.handoff_audit import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
