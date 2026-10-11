"""Re-export of ``dev10x.tasks.session.task_index`` at its pre-ADR-0034 path (GH-1541).

The old name is the same module object as the new one, so every import and
patch target keeps working; see ``dev10x.core.module_alias``.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_module

if TYPE_CHECKING:
    from dev10x.tasks.session.task_index import *  # noqa: F403

alias_module(old=__name__, new="dev10x.tasks.session.task_index")
