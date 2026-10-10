"""Re-export of ``dev10x.core.platform`` at its pre-ADR-0034 path (GH-1535).

Every ``dev10x.platform.<name>`` resolves to the same module object as
``dev10x.core.platform.<name>``; see ``dev10x.core.module_alias``.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_package

if TYPE_CHECKING:
    from dev10x.core.platform import (
        PlatformCatalog,
        PlatformConfig,
        PlatformRepository,
        known_platforms,
        registered_platforms,
    )

alias_package(old=__name__, new="dev10x.core.platform")

__all__ = [
    "PlatformCatalog",
    "PlatformConfig",
    "PlatformRepository",
    "known_platforms",
    "registered_platforms",
]
