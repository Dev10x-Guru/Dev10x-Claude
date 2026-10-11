"""Re-export of ``dev10x.coding.github`` at its pre-ADR-0034 path (GH-1546).

``dev10x.github`` is the same module object as ``dev10x.coding.github``,
and every ``dev10x.github.<name>`` submodule resolves to the module the new
path loads. Facade patch targets, the capability-module seams of ADR-0027
and server_cli's tool registrations therefore keep working. The core-owned
``_gateway``, ``app_api`` and ``app_auth`` resolve through their alias
files inside the coding package to ``dev10x.core.github``; see
``dev10x.core.module_alias``.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_package

if TYPE_CHECKING:
    from dev10x.coding.github import *  # noqa: F403

alias_package(old=__name__, new="dev10x.coding.github")
