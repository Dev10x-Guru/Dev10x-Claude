"""Re-export of ``dev10x.core.config`` at its pre-ADR-0034 path (GH-1535).

Every ``dev10x.config.<name>`` resolves to the same module object as
``dev10x.core.config.<name>``; see ``dev10x.core.module_alias``.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_package

if TYPE_CHECKING:
    from dev10x.core.config import load_config

alias_package(old=__name__, new="dev10x.core.config")

__all__ = ["load_config"]
