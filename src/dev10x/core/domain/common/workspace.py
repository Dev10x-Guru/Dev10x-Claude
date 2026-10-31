"""Workspace value object — a worktree or project root (PAP-3, GH-800).

Names the thing the permission renderer scopes rules to: the checkout
root plus the well-known directories that must be registered under
``permissions.additionalDirectories`` for Write/Edit/Read tools to
operate without per-call prompts (GH-40, GH-254).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Known worktree layouts, each capturing the worktree name (GH-1666):
# ``<repo>/.worktrees/<name>`` and herdr's ``<herdr-root>/worktrees/<repo>/<name>``
# under ``/work/.herdr`` or ``~/.herdr``. A layout outside both is still a
# worktree to git; callers that can afford I/O ask git, this pure value
# object only names the shapes it can read from the path.
_WORKTREE_LAYOUTS = (
    re.compile(r"/\.worktrees/(?P<name>[^/]+)"),
    re.compile(r"/\.herdr/worktrees/[^/]+/(?P<name>[^/]+)"),
)


def _layout_match(root: str) -> re.Match[str] | None:
    for layout in _WORKTREE_LAYOUTS:
        match = layout.search(root)
        if match is not None:
            return match
    return None


@dataclass(frozen=True)
class Workspace:
    """One checkout root the rendered settings apply to."""

    root: str
    additional_directories: tuple[str, ...] = ()

    @property
    def is_worktree(self) -> bool:
        return _layout_match(self.root) is not None

    @property
    def worktree_name(self) -> str:
        """The worktree's own name segment; empty for a main checkout."""
        match = _layout_match(self.root)
        return match.group("name") if match is not None else ""

    @classmethod
    def from_config(cls, *, root: str, config: dict) -> Workspace:
        """Build a workspace from a config's ``workspace_directories`` list.

        Non-list values and non-string entries are skipped, mirroring
        the defensive parsing of the catalog loaders.
        """
        entries = config.get("workspace_directories")
        if not isinstance(entries, list):
            return cls(root=root)
        directories = tuple(entry for entry in entries if isinstance(entry, str))
        return cls(root=root, additional_directories=directories)


__all__ = ["Workspace"]
