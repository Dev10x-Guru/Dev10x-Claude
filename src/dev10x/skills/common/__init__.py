"""Re-export of ``dev10x.coding.skills.common`` at its pre-ADR-0034 path (GH-1546).

Every ``dev10x.skills.common.<name>`` resolves to the same module object as
``dev10x.coding.skills.common.<name>``; see ``dev10x.core.module_alias``.
"""

from dev10x.core.module_alias import alias_package

alias_package(old=__name__, new="dev10x.coding.skills.common")
