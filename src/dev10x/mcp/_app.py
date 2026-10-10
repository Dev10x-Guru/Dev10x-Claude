"""Re-export of ``dev10x.core.mcp._app`` at its pre-ADR-0034 path (GH-1539).

The old name is the same module object as the new one, so every tool
module registers on the one ``server`` and patch targets stay shared; see
``dev10x.core.module_alias``.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_module

if TYPE_CHECKING:
    from dev10x.core.mcp._app import *  # noqa: F403

alias_module(old=__name__, new="dev10x.core.mcp._app")
