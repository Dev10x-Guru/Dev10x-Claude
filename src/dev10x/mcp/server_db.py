"""Re-export of ``dev10x.db.mcp.server_db`` at its pre-ADR-0034 path (GH-1543).

The old name is the same module object as the new one, so the ``server``
object, ``main`` and every patch target keep working; see
``dev10x.core.module_alias``. The tool registers in the db module.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_module

if TYPE_CHECKING:
    from dev10x.db.mcp.server_db import *  # noqa: F403

alias_module(old=__name__, new="dev10x.db.mcp.server_db")
