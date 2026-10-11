"""Re-export of ``dev10x.teach.audit`` at its pre-ADR-0034 path (GH-1544).

Every ``dev10x.audit.<name>`` resolves to the same module object as
``dev10x.teach.audit.<name>``, so the hook log readers, the audit MCP
tools and every patch target keep working; see ``dev10x.core.module_alias``.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_package

if TYPE_CHECKING:
    from dev10x.teach.audit import (
        analyze_actions,
        analyze_permissions,
        extract_session,
        hook_log_path,
        hook_recent,
        iter_records,
        prune,
        summarize,
    )

alias_package(old=__name__, new="dev10x.teach.audit")

__all__ = [
    "analyze_actions",
    "analyze_permissions",
    "extract_session",
    "hook_log_path",
    "hook_recent",
    "iter_records",
    "prune",
    "summarize",
]
