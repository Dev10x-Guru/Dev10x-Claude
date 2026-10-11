"""Re-export of ``dev10x.comm.skills.notifications`` at its pre-ADR-0034 path (GH-1542).

Every ``dev10x.skills.notifications.<name>`` resolves to the same module
object as ``dev10x.comm.skills.notifications.<name>``, so the skill scripts,
the ``dev10x skill`` commands and every patch target keep working; see
``dev10x.core.module_alias``.
"""

from dev10x.core.module_alias import alias_package

alias_package(old=__name__, new="dev10x.comm.skills.notifications")
