"""Re-export of ``dev10x.core.github.app_api`` at its pre-ADR-0034 path (GH-1536).

``dev10x.github`` is this package under its old name (GH-1546), so this
file is what ``dev10x.github.app_api`` resolves to: the same module object
as the core one, so patch targets stay shared; see
``dev10x.core.module_alias``.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_module

if TYPE_CHECKING:
    from dev10x.core.github.app_api import *  # noqa: F403

alias_module(old=__name__, new="dev10x.core.github.app_api")
