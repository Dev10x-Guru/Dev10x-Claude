"""Re-export of ``dev10x.core.skills.permission`` at its pre-ADR-0034 path (GH-1540).

Every ``dev10x.skills.permission.<name>`` resolves to the same module
object as ``dev10x.core.skills.permission.<name>``; see
``dev10x.core.module_alias``.
"""

from dev10x.core.module_alias import alias_package

alias_package(old=__name__, new="dev10x.core.skills.permission")
