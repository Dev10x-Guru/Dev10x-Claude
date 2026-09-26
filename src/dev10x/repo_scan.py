"""Shared repo-wide file walker for the lint-style detectors (GH-1460).

`dev10x.subprocess_timeouts` (GH-1414) and `dev10x.dependency_pins`
(GH-916) each scan the whole repository tree for a different offense,
but the walk itself — which directories to skip, which files count,
how symlinks are handled — was byte-identical in both modules. The
newer detector was deliberately modelled on the older one so the two
guards read alike; this module is that mirroring taken one step
further, from matching *shape* to sharing *code*, so the exclusion set
and the walk logic cannot drift between the two call sites the way two
copies of a comment already had.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

# `worktrees` covers `.claude/worktrees/` (agent isolation trees) and a
# project's `.worktrees/` — each is a full checkout of this same repo, so
# scanning them re-reports every finding once per tree and lets leftover
# trees fail the canonical lint suite repo-wide until someone prunes them.
SKIPPED_DIRS = frozenset(
    {".git", ".venv", "node_modules", "__pycache__", "dist", "build", "worktrees"}
)


def walk_repository(root: Path, *, suffixes: Iterable[str]) -> list[Path]:
    """Return every scannable file under ``root``, sorted for stable output.

    Excludes symlinks: ``Path.rglob()`` follows symlinked directories on
    this project's floor Python (3.12 — the ``recurse_symlinks`` opt-out
    landed in 3.13), so an unguarded scan could read a symlink's target
    content or hang on a cycle. Each caller passes its own suffix set —
    ``subprocess_timeouts`` scans one suffix (``.py``), ``dependency_pins``
    scans three (``.py``, ``.toml``, ``.sh``) — so ``suffixes`` stays a
    caller argument rather than a module constant.
    """
    suffix_set = frozenset(suffixes)
    return sorted(
        path
        for path in root.rglob("*")
        if path.suffix in suffix_set
        and path.is_file()
        and not path.is_symlink()
        and not SKIPPED_DIRS.intersection(path.relative_to(root).parts)
    )


__all__ = ["SKIPPED_DIRS", "walk_repository"]
