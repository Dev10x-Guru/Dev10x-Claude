"""Re-export of ``dev10x.core.spec`` at its pre-ADR-0034 path (GH-1537).

Every ``dev10x.spec.<name>`` resolves to the same module object as
``dev10x.core.spec.<name>``; see ``dev10x.core.module_alias``.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_package

if TYPE_CHECKING:
    from dev10x.core.spec import DriftKind, DriftReport, DriftSignal, detect_drift

alias_package(old=__name__, new="dev10x.core.spec")

__all__ = ["DriftKind", "DriftReport", "DriftSignal", "detect_drift"]
