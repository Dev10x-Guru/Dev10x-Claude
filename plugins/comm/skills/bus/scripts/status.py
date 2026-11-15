#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Thin shim — delegates to dev10x.comm.skills.bus.status."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from core_src import add_core_src  # noqa: E402

add_core_src(script=Path(__file__))

from dev10x.comm.skills.bus.status import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
