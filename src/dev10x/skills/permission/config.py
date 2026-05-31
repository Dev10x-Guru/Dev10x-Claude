"""Shared config resolution for permission skills (GH-246 H12).

The permission skills each search a slightly different tier of YAML
config files but parse them identically. ``resolve_config`` holds the
search-and-error logic once; ``parse_config`` holds the parse. Each
skill keeps a thin ``find_config``/``load_config`` wrapper so existing
``mod.find_config()`` / ``mod.load_config()`` callers are unchanged.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml


def resolve_config(candidates: list[Path], create_path: Path | None = None) -> Path:
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    message = "ERROR: No config found."
    if create_path is not None and candidates:
        message = (
            f"ERROR: No config found. Create {create_path}\nor ensure {candidates[-1]} exists."
        )
    print(message, file=sys.stderr)
    sys.exit(1)


def parse_config(config_path: Path) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)
