#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.0,<2", "pyyaml>=6.0,<7", "msgpack>=1.0,<2", "click>=8.0,<9"]
# ///
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from dev10x.mcp.server_cli import main

if __name__ == "__main__":
    main()
