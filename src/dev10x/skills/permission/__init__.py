"""Re-export of ``dev10x.core.skills.permission`` at its pre-ADR-0034 path (GH-1540).

Every ``dev10x.skills.permission.<name>`` resolves to the same module
object as ``dev10x.core.skills.permission.<name>``; see
``dev10x.core.module_alias``.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_package

if TYPE_CHECKING:
    from dev10x.core.skills.permission import (
        clean_project_files,
        enumerate_mcp,
        grant,
        ignore_session_state,
        merge_worktree_permissions,
        migrate_config,
        policy_audit,
        promote,
        provenance,
        safety_keys,
        update_paths,
    )

alias_package(old=__name__, new="dev10x.core.skills.permission")

__all__ = [
    "clean_project_files",
    "enumerate_mcp",
    "grant",
    "ignore_session_state",
    "merge_worktree_permissions",
    "migrate_config",
    "policy_audit",
    "promote",
    "provenance",
    "safety_keys",
    "update_paths",
]
