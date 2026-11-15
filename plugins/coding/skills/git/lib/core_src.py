"""Find core's ``src/`` from a coding skill script, wherever dev10x-coding sits
(GH-1572).

Several coding scripts are thin uv-script shims over ``dev10x`` modules that
ship with core. Before ADR-0034 B9 they lived under core's own root, so
``<root>/src`` was always beside them. In ``dev10x-coding`` they can run from
three layouts, tried in order:

1. a pre-split core install, ``<root>/skills/<skill>/scripts``;
2. a checkout or marketplace clone,
   ``<repo>/plugins/coding/skills/<skill>/scripts``;
3. an installed satellite, ``<cache>/<publisher>/dev10x-coding/<ver>/...``,
   whose core sits beside it at ``<cache>/<publisher>/dev10x/<newest ver>``.

A satellite cannot import another satellite, so this mirrors
``dev10x-comm``'s ``skills/bus/lib/core_src.py`` line for line. Every coding
script shares this one copy under the ``git`` skill.

Standard library only: it runs before ``dev10x`` is importable.
"""

from __future__ import annotations

import sys
from pathlib import Path

CORE_PLUGIN_NAME = "dev10x"
PACKAGE = "dev10x"
SRC = "src"


def _version_key(name: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in name.split("."))
    except ValueError:
        return (0,)


def _newest_version(*, versions_dir: Path) -> Path | None:
    if not versions_dir.is_dir():
        return None
    versions = sorted(versions_dir.iterdir(), key=lambda path: _version_key(path.name))
    return versions[-1] if versions else None


def core_src_candidates(*, script: Path) -> list[Path]:
    plugin_root = script.resolve().parents[3]
    candidates = [plugin_root / SRC, plugin_root.parents[1] / SRC]
    core_version = _newest_version(versions_dir=plugin_root.parents[1] / CORE_PLUGIN_NAME)
    if core_version is not None:
        candidates.append(core_version / SRC)
    return candidates


def find_core_src(*, script: Path) -> Path | None:
    return next(
        (
            candidate
            for candidate in core_src_candidates(script=script)
            if (candidate / PACKAGE).is_dir()
        ),
        None,
    )


def add_core_src(*, script: Path) -> None:
    found = find_core_src(script=script)
    if found is not None and str(found) not in sys.path:
        sys.path.insert(0, str(found))
