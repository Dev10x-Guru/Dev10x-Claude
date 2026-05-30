"""GH-115: cluster session-accessed paths by common ancestor.

Used by Dev10x:permission-investigator / Dev10x:plugin-doctor to detect
user-wide directories (notes vaults, scratch dirs) that lack
both an `additionalDirectories` entry and path-scoped tool
allow rules. The output is a list of coherent patches — one
per cluster — bundling all four pieces (additionalDirectories,
Read/Write/Edit, find/ls/grep) so the user doesn't have to
approve them one-by-one.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dev10x.domain.common.allow_rule import AllowRule

# Project-internal paths skip clustering — they're already covered
# by the project root and don't need user-wide allow rules.
PROJECT_ROOT_MARKERS = ("/work/", "/src/", "/.worktrees/")

# Paths Claude Code already grants implicitly — never propose them.
ALWAYS_ALLOWED_PREFIXES = ("/tmp/", "/var/tmp/")


@dataclass
class PathCluster:
    ancestor: str
    paths: list[str] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.paths)


@dataclass
class CoveragePatch:
    """One coherent allow-rule bundle for a single ancestor."""

    ancestor: str
    additional_directory: str
    rules: list[str] = field(default_factory=list)
    placement: str = "user"  # "user" or "project"


def find_common_ancestor(paths: list[str], *, depth: int = 2) -> str:
    """Return the common ancestor of ``paths`` up to ``depth`` segments
    below the user's home or system root.

    Example: ``find_common_ancestor(["/home/u/notes/a.md", "/home/u/notes/b.md"])``
    returns ``"/home/u/notes"``.
    """
    if not paths:
        return ""
    split_paths = [Path(p).parts for p in paths]
    common: list[str] = []
    for parts in zip(*split_paths, strict=False):
        if len(set(parts)) == 1:
            common.append(parts[0])
        else:
            break
    ancestor = os.path.join(*common) if common else ""
    if depth and ancestor:
        home = os.path.expanduser("~")
        if ancestor.startswith(home):
            rel = ancestor[len(home) + 1 :].split(os.sep)
            ancestor = os.path.join(home, *rel[:depth]) if rel else home
    return ancestor


def cluster_paths(paths: list[str], *, depth: int = 2) -> list[PathCluster]:
    """Group ``paths`` into clusters sharing a common ancestor.

    Paths under ``ALWAYS_ALLOWED_PREFIXES`` or matching
    ``PROJECT_ROOT_MARKERS`` are filtered out — only user-wide
    directories outside the project warrant a cluster patch.
    """
    candidates = [p for p in paths if _is_clusterable(path=p)]
    if not candidates:
        return []

    buckets: dict[str, list[str]] = {}
    for path in candidates:
        anc = find_common_ancestor(paths=[path], depth=depth)
        if not anc:
            continue
        buckets.setdefault(anc, []).append(path)

    return [PathCluster(ancestor=a, paths=p) for a, p in buckets.items() if len(p) >= 1]


def _is_clusterable(*, path: str) -> bool:
    if not path:
        return False
    if any(path.startswith(prefix) for prefix in ALWAYS_ALLOWED_PREFIXES):
        return False
    if any(marker in path for marker in PROJECT_ROOT_MARKERS):
        return False
    return True


def propose_patch(*, cluster: PathCluster) -> CoveragePatch:
    """Build a CoveragePatch covering the four typical entry points
    a user-wide directory needs: additionalDirectories + Read/Write/
    Edit rules + Bash discovery (find/ls/grep).

    Path placement defaults to ``user`` for paths under the user's
    home; project-adjacent paths return ``placement="project"``.
    """
    ancestor = cluster.ancestor
    home = os.path.expanduser("~")
    placement = "user" if ancestor.startswith(home) else "project"

    return CoveragePatch(
        ancestor=ancestor,
        additional_directory=ancestor,
        placement=placement,
        rules=[
            str(AllowRule.read(f"{ancestor}/**")),
            str(AllowRule.write(f"{ancestor}/**")),
            str(AllowRule.edit(f"{ancestor}/**")),
            str(AllowRule.bash(f"find {ancestor}:*")),
            str(AllowRule.bash(f"ls {ancestor}:*")),
            str(AllowRule.bash(f"grep -r {ancestor}:*")),
        ],
    )
