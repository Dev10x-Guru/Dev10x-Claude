"""Re-export of ``dev10x.coding.monitor`` at its pre-ADR-0034 path (GH-1546).

``dev10x.monitor`` is the same module object as ``dev10x.coding.monitor``,
so the CI-status MCP tool and every patch target keep working; see
``dev10x.core.module_alias``.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_package

if TYPE_CHECKING:
    from dev10x.coding.monitor import ci_check_status

alias_package(old=__name__, new="dev10x.coding.monitor")

__all__ = ["ci_check_status"]
