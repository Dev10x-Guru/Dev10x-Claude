"""Re-export of ``dev10x.core.subprocess_utils`` at its pre-ADR-0034 path (GH-1534).

The old name is the same module object as the new one, so patch targets
and the effective-cwd wiring stay shared; see ``dev10x.core.module_alias``.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_module

if TYPE_CHECKING:
    from dev10x.core.subprocess_utils import *  # noqa: F403

alias_module(old=__name__, new="dev10x.core.subprocess_utils")
