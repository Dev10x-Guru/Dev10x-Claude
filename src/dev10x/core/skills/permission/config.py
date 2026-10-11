"""Shared config resolution for permission skills (GH-246 H12).

The permission skills each search a slightly different tier of YAML
config files but parse them identically. ``resolve_config`` holds the
search-and-error logic once; ``parse_config`` holds the parse. Each
skill keeps a thin ``find_config``/``load_config`` wrapper so existing
``mod.find_config()`` / ``mod.load_config()`` callers are unchanged.
"""

from __future__ import annotations

import logging
from pathlib import Path

from dev10x.domain.common.command_spellings import expand_spellings
from dev10x.domain.common.result import Result, err, ok
from dev10x.skills.permission.catalog_paths import load_catalog_document

log = logging.getLogger(__name__)


def resolve_config(
    candidates: list[Path],
    create_path: Path | None = None,
) -> Result[Path]:
    for candidate in candidates:
        if candidate.is_file():
            return ok(candidate)
    message = "No config found."
    if create_path is not None and candidates:
        message = f"No config found. Create {create_path} or ensure {candidates[-1]} exists."
    log.error(message)
    return err(message)


def parse_config(config_path: Path) -> dict:
    return expand_spellings(load_catalog_document(catalog_path=config_path))
