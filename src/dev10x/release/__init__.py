"""Re-export of ``dev10x.coding.release`` at its pre-ADR-0034 path (GH-1546).

``dev10x.release`` is the same module object as ``dev10x.coding.release``,
so the release MCP tool and every patch target keep working; see
``dev10x.core.module_alias``.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_package

if TYPE_CHECKING:
    from dev10x.coding.release import collect_prs

alias_package(old=__name__, new="dev10x.coding.release")

__all__ = ["collect_prs"]
