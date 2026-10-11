"""Re-export of ``dev10x.comm.skills.bus`` at its pre-ADR-0034 path (GH-1542).

Every ``dev10x.skills.bus.<name>`` resolves to the same module object as
``dev10x.comm.skills.bus.<name>``, so the skill scripts and every patch
target keep working; see ``dev10x.core.module_alias``.
"""

from dev10x.core.module_alias import alias_package

alias_package(old=__name__, new="dev10x.comm.skills.bus")
