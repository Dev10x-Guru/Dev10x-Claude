"""Re-export of ``dev10x.core.permission`` at its pre-ADR-0034 path (GH-1538).

Every ``dev10x.permission.<name>`` resolves to the same module object as
``dev10x.core.permission.<name>``; see ``dev10x.core.module_alias``.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_package

if TYPE_CHECKING:
    from dev10x.core.permission import (
        catalog_denies,
        catalog_gap,
        grant,
        load_permission_context,
        triage,
        update_paths,
    )

alias_package(old=__name__, new="dev10x.core.permission")

__all__ = [
    "catalog_denies",
    "catalog_gap",
    "grant",
    "load_permission_context",
    "triage",
    "update_paths",
]
