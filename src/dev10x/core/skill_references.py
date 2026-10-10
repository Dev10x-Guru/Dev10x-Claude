"""Inventory of ``dev10x:<skill>`` invocation references (ADR-0034, GH-1531).

Stage B rewrites ``dev10x:<skill>`` to ``<plugin>:<skill>`` one plugin
at a time. Counting every reference per skill before and after a rename
is how a move PR proves nothing was missed.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from dev10x.repo_scan import walk_repository

REFERENCE = re.compile(r"(?<![\w.-])[Dd]ev10x:([a-z0-9][a-z0-9-]*[a-z0-9])(?![\w-])")
SCANNED_SUFFIXES = (".md", ".yaml", ".yml", ".json", ".py", ".sh")
SCANNED_DIRS = ("skills", "docs", "references", "agents", "commands")
SCANNED_FILES = ("src/dev10x/validators/command-skill-map.yaml",)


def references_in(*, text: str) -> list[str]:
    return REFERENCE.findall(text)


def scanned_paths(*, root: Path) -> list[Path]:
    paths: list[Path] = []
    for directory in SCANNED_DIRS:
        if (root / directory).is_dir():
            paths.extend(walk_repository(root / directory, suffixes=SCANNED_SUFFIXES))
    paths.extend(root / file for file in SCANNED_FILES if (root / file).is_file())
    return paths


def count_references(*, paths: Iterable[Path]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for path in paths:
        counts.update(references_in(text=path.read_text(errors="replace")))
    return dict(sorted(counts.items()))


def unknown_references(*, counts: dict[str, int], skills: Iterable[str]) -> list[str]:
    return sorted(set(counts) - set(skills))


__all__ = [
    "REFERENCE",
    "SCANNED_DIRS",
    "SCANNED_FILES",
    "SCANNED_SUFFIXES",
    "count_references",
    "references_in",
    "scanned_paths",
    "unknown_references",
]
