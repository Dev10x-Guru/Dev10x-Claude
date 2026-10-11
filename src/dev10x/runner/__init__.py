"""Re-export of ``dev10x.coding.runner`` at its pre-ADR-0034 path (GH-1546).

``dev10x.runner`` is the same module object as ``dev10x.coding.runner``, so
the run_tests / run_node_tests tools and every patch target keep working;
see ``dev10x.core.module_alias``.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_package

if TYPE_CHECKING:
    from dev10x.coding.runner import resolve_test_extras, run_node_tests, run_tests

alias_package(old=__name__, new="dev10x.coding.runner")

__all__ = ["resolve_test_extras", "run_node_tests", "run_tests"]
