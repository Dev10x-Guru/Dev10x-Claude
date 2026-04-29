#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml"]
# ///
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from dev10x.skills.audit.extract_session import *  # noqa: F401, F403
from dev10x.skills.audit.extract_session import main

if __name__ == "__main__":
    main()
