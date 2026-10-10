"""Re-export of ``dev10x.core.utilities`` at its pre-ADR-0034 path (GH-1535).

Every ``dev10x.utilities.<name>`` resolves to the same module object as
``dev10x.core.utilities.<name>``; see ``dev10x.core.module_alias``.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_package

if TYPE_CHECKING:
    from dev10x.core.utilities import mktmp

alias_package(old=__name__, new="dev10x.core.utilities")

__all__ = ["mktmp"]
