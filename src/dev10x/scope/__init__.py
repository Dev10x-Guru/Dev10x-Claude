"""Re-export of ``dev10x.scoping.scope`` at its pre-ADR-0034 path (GH-1545).

Every ``dev10x.scope.<name>`` resolves to the same module object as
``dev10x.scoping.scope.<name>``, so the ticket-scope API and every patch
target keep working; see ``dev10x.core.module_alias``.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_package

if TYPE_CHECKING:
    from dev10x.scoping.scope import RuleEntry, parse_index, render_norms, render_safeguards

alias_package(old=__name__, new="dev10x.scoping.scope")

__all__ = ["RuleEntry", "parse_index", "render_norms", "render_safeguards"]
