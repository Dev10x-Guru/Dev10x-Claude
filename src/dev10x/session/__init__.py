"""Old path for the session modules now in ``dev10x.core.session`` (GH-1538).

Each moved ``dev10x.session.<name>`` is the same module object as
``dev10x.core.session.<name>``, so every import and patch target keeps
working. ``task_index`` belongs to the tasks namespace and still lives
here; see ``dev10x.core.module_alias.alias_submodules``.
"""

from __future__ import annotations

from dev10x.core.module_alias import alias_submodules
from dev10x.core.session.service import SessionService, SessionServiceError

alias_submodules(old=__name__, new="dev10x.core.session")

__all__ = [
    "SessionService",
    "SessionServiceError",
]
