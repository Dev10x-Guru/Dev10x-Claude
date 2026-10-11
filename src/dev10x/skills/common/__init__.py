"""Re-export of ``dev10x.core.skills.common`` at its pre-ADR-0034 path (GH-1547).

Every ``dev10x.skills.common.<name>`` resolves to the same module object as
``dev10x.core.skills.common.<name>``; see ``dev10x.core.module_alias``.
"""

from dev10x.core.module_alias import alias_package

alias_package(old=__name__, new="dev10x.core.skills.common")
