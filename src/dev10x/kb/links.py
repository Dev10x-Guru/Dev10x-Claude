"""Relative Markdown links between vault notes (GH-1985).

Obsidian resolves a relative Markdown link only when spaces and
parentheses are percent-encoded; a hand-typed link with a raw space is
silently broken. Every link the harvest writes goes through here.
"""

from __future__ import annotations

import os
from pathlib import Path

_ESCAPES = {" ": "%20", "(": "%28", ")": "%29", "<": "%3C", ">": "%3E", "#": "%23", "?": "%3F"}


def encode(path: str) -> str:
    return "".join(_ESCAPES.get(char, char) for char in path)


def relative_link(*, source: Path, target: Path, text: str | None = None) -> str:
    """``[text](relative/path)`` from the note ``source`` to ``target``."""
    relative = Path(os.path.relpath(target, start=source.parent)).as_posix()
    return f"[{text or target.stem}]({encode(relative)})"
