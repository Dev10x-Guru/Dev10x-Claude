"""Re-export of ``dev10x.teach.skills.audit`` at its pre-ADR-0034 path (GH-1544).

Every ``dev10x.skills.audit.<name>`` resolves to the same module object as
``dev10x.teach.skills.audit.<name>``, so the skill-audit scripts, the
``bin/check-*`` hooks and every patch target keep working; see
``dev10x.core.module_alias``.
"""

from dev10x.core.module_alias import alias_package

alias_package(old=__name__, new="dev10x.teach.skills.audit")
