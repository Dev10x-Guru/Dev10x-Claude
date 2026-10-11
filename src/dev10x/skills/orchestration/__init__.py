"""Re-export of ``dev10x.coding.skills.orchestration`` at its pre-ADR-0034 path (GH-1546).

Every ``dev10x.skills.orchestration.<name>`` resolves to the same module
object as ``dev10x.coding.skills.orchestration.<name>``; see
``dev10x.core.module_alias``.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_package

if TYPE_CHECKING:
    from dev10x.coding.skills.orchestration import *  # noqa: F403

alias_package(old=__name__, new="dev10x.coding.skills.orchestration")
