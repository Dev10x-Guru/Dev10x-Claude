"""Re-export of ``dev10x.core.skills.permission_investigator`` at its pre-ADR-0034 path.

Every ``dev10x.skills.permission_investigator.<name>`` resolves to the same
module object as ``dev10x.core.skills.permission_investigator.<name>``
(GH-1540); see ``dev10x.core.module_alias``.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_package

if TYPE_CHECKING:
    from dev10x.core.skills.permission_investigator import (
        Delta,
        Matrix,
        PermissionDeltaQuery,
        load_matrix_from_state,
    )

alias_package(old=__name__, new="dev10x.core.skills.permission_investigator")

__all__ = [
    "Delta",
    "Matrix",
    "PermissionDeltaQuery",
    "load_matrix_from_state",
]
