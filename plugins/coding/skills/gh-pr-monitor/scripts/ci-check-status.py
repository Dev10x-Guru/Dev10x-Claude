#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml>=6.0,<7"]
# ///
"""Thin shim — delegates to dev10x.coding.skills.monitor.ci_check_status."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "git" / "lib"))

from core_src import add_core_src  # noqa: E402

add_core_src(script=Path(__file__))

from dev10x.coding.skills.monitor.ci_check_status import *  # noqa: E402, F401, F403
from dev10x.coding.skills.monitor.ci_check_status import main  # noqa: E402

if __name__ == "__main__":
    main()
