"""Find core's ``src/`` from a bus script, wherever dev10x-comm sits (GH-1567).

The bus scripts are thin shims over ``dev10x.comm.skills.bus``, which ships
with core. Before ADR-0034 B4 they lived under core's own root, so
``<root>/src`` was always beside them. In ``dev10x-comm`` they can run
from three layouts, tried in order:

1. a pre-split core install, ``<root>/skills/bus/scripts``;
2. a checkout or marketplace clone, ``<repo>/plugins/comm/skills/bus/scripts``;
3. an installed satellite, ``<cache>/<publisher>/dev10x-comm/<ver>/...``,
   whose core sits beside it at ``<cache>/<publisher>/dev10x/<newest ver>``.

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
