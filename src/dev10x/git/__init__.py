"""Re-export of ``dev10x.coding.git`` at its pre-ADR-0034 path (GH-1546).

``dev10x.git`` is the same module object as ``dev10x.coding.git``, so the
git MCP tools and every ``dev10x.git.<name>`` patch target keep working;
see ``dev10x.core.module_alias``.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_package

if TYPE_CHECKING:
    from dev10x.coding.git import (
        create_worktree,
        mass_rewrite,
        next_worktree_name,
        push_safe,
        qualify_base_ref,
        rebase_groom,
        setup_aliases,
        start_split_rebase,
    )

alias_package(old=__name__, new="dev10x.coding.git")

__all__ = [
    "create_worktree",
    "mass_rewrite",
    "next_worktree_name",
    "push_safe",
    "qualify_base_ref",
    "rebase_groom",
    "setup_aliases",
    "start_split_rebase",
]
