"""Old path for the hook modules now in ``dev10x.core.hooks`` (GH-1538).

Each moved ``dev10x.hooks.<name>`` is the same module object as
``dev10x.core.hooks.<name>``, so the ``hooks/scripts`` entry points and
every patch target keep working. ``task_plan_sync`` and ``task_guard``
belong to the tasks namespace; their files here alias
``dev10x.tasks.hooks.<name>`` (GH-1541, GH-1556). See
``dev10x.core.module_alias.alias_submodules``.
"""

from dev10x.core.module_alias import alias_submodules

alias_submodules(old=__name__, new="dev10x.core.hooks")
