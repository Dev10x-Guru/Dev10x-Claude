"""Re-export of ``dev10x.core.mcp.gate_tools`` at its pre-ADR-0034 path (GH-1539).

The old name is the same module object as the new one, so server_cli's
star import and every patch target keep working; see
``dev10x.core.module_alias``. The tools register in the core module.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_module

if TYPE_CHECKING:
    from dev10x.core.mcp.gate_tools import *  # noqa: F403

alias_module(old=__name__, new="dev10x.core.mcp.gate_tools")
