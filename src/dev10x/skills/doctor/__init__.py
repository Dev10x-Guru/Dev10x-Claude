"""Re-export of ``dev10x.core.skills.doctor`` at its pre-ADR-0034 path (GH-1540).

Every ``dev10x.skills.doctor.<name>`` (strategies included) resolves to the
same module object as ``dev10x.core.skills.doctor.<name>``; see
``dev10x.core.module_alias``.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_package

if TYPE_CHECKING:
    from dev10x.core.skills.doctor import Context, Finding, Remediation, Severity, Strategy

alias_package(old=__name__, new="dev10x.core.skills.doctor")

__all__ = [
    "Context",
    "Finding",
    "Remediation",
    "Severity",
    "Strategy",
]
