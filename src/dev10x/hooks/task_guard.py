"""Re-export of ``dev10x.tasks.hooks.task_guard`` at its pre-ADR-0034 path (GH-1556).

The old name is the same module object as the new one, so the
``hooks/scripts/task-guard.py`` entry point and every patch target keep
working; see ``dev10x.core.module_alias``.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_module

if TYPE_CHECKING:
    from dev10x.tasks.hooks.task_guard import *  # noqa: F403

alias_module(old=__name__, new="dev10x.tasks.hooks.task_guard")
