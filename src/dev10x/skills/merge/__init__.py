"""Re-export of ``dev10x.coding.skills.merge`` at its pre-ADR-0034 path (GH-1546).

Every ``dev10x.skills.merge.<name>`` resolves to the same module object as
``dev10x.coding.skills.merge.<name>``, so the gh-pr-merge scripts and every
patch target keep working; see ``dev10x.core.module_alias``.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_package

if TYPE_CHECKING:
    from dev10x.coding.skills.merge import (
        HandoffAudit,
        audit_handoff_report,
        commit_ticket_ids,
        fixes_links,
        names_observed_value,
        reconcile_fixes_links,
    )

alias_package(old=__name__, new="dev10x.coding.skills.merge")

__all__ = [
    "HandoffAudit",
    "audit_handoff_report",
    "commit_ticket_ids",
    "fixes_links",
    "names_observed_value",
    "reconcile_fixes_links",
]
