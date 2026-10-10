"""Re-export of ``dev10x.core.mcp.wiring`` at its pre-ADR-0034 path (GH-1539).

The old name is the same module object as the new one; see
``dev10x.core.module_alias``.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_module

if TYPE_CHECKING:
    from dev10x.core.mcp.wiring import *  # noqa: F403

alias_module(old=__name__, new="dev10x.core.mcp.wiring")
