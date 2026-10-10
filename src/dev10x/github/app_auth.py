"""Re-export of ``dev10x.core.github.app_auth`` at its pre-ADR-0034 path (GH-1536).

The old name is the same module object as the new one, so patch targets
and the per-repo token cache stay shared; see ``dev10x.core.module_alias``.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_module

if TYPE_CHECKING:
    from dev10x.core.github.app_auth import *  # noqa: F403

alias_module(old=__name__, new="dev10x.core.github.app_auth")
