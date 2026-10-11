"""Re-export of ``dev10x.coding.skills.foreman`` at its pre-ADR-0034 path (GH-1546).

Every ``dev10x.skills.foreman.<name>`` resolves to the same module object as
``dev10x.coding.skills.foreman.<name>``, so the `dev10x foreman watch` CLI
and every patch target keep working; see ``dev10x.core.module_alias``.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_package

if TYPE_CHECKING:
    from dev10x.coding.skills.foreman import *  # noqa: F403

alias_package(old=__name__, new="dev10x.coding.skills.foreman")
