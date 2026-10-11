"""Re-export of ``dev10x.tasks.plan`` at its pre-ADR-0034 path (GH-1541).

Every ``dev10x.plan.<name>`` resolves to the same module object as
``dev10x.tasks.plan.<name>``; see ``dev10x.core.module_alias``.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_package

if TYPE_CHECKING:
    from dev10x.tasks.plan import archive, json_summary, set_context

alias_package(old=__name__, new="dev10x.tasks.plan")

__all__ = ["archive", "json_summary", "set_context"]
