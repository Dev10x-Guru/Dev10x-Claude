"""Re-export of ``dev10x.coding.mcp.monitor_tools`` at its pre-ADR-0034 path (GH-1549).

The old name is the same module object as the new one, so every patch
target keeps working; see ``dev10x.core.module_alias``. The tools
register in the coding module.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_module

if TYPE_CHECKING:
    from dev10x.coding.mcp.monitor_tools import *  # noqa: F403

alias_module(old=__name__, new="dev10x.coding.mcp.monitor_tools")
