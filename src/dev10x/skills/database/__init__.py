"""Re-export of ``dev10x.db.skills.database`` at its pre-ADR-0034 path (GH-1543).

Every ``dev10x.skills.database.<name>`` resolves to the same module object
as ``dev10x.db.skills.database.<name>``; see ``dev10x.core.module_alias``.
"""

from dev10x.core.module_alias import alias_package

alias_package(old=__name__, new="dev10x.db.skills.database")
