"""Workspace value object — a worktree or project root (PAP-3, GH-800).

Names the thing the permission renderer scopes rules to: the checkout
root plus the well-known directories that must be registered under
``permissions.additionalDirectories`` for Write/Edit/Read tools to
operate without per-call prompts (GH-40, GH-254).
"""

from __future__ import annotations

from dataclasses import dataclass

_WORKTREES_SEGMENT = "/.worktrees/"


@dataclass(frozen=True)
class Workspace:
    """One checkout root the rendered settings apply to."""

    root: str
    additional_directories: tuple[str, ...] = ()

    @property
    def is_worktree(self) -> bool:
        return _WORKTREES_SEGMENT in self.root

    @property
    def worktree_name(self) -> str:
        """The ``.worktrees/<name>`` segment; empty for a main checkout."""
        if not self.is_worktree:
            return ""
        tail = self.root.split(_WORKTREES_SEGMENT, 1)[1]
        return tail.split("/", 1)[0]

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
