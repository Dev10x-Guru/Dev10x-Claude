"""Re-export of ``dev10x.core.validators`` at its pre-ADR-0034 path (GH-1538).

Every ``dev10x.validators.<name>`` resolves to the same module object as
``dev10x.core.validators.<name>``, so the ``ValidatorSpec.module_path``
strings and every patch target keep working; see
``dev10x.core.module_alias``.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_package

if TYPE_CHECKING:
    from dev10x.core.validators import (
        DisableListFilter,
        ExperimentalFilter,
        ProfileFilter,
        ValidatorChain,
        ValidatorRegistry,
        ValidatorSpec,
        get_chain,
        get_registry,
        get_validators,
        reset_registry,
    )

alias_package(old=__name__, new="dev10x.core.validators")

__all__ = [
    "DisableListFilter",
    "ExperimentalFilter",
    "ProfileFilter",
    "ValidatorChain",
    "ValidatorRegistry",
    "ValidatorSpec",
    "get_chain",
    "get_registry",
    "get_validators",
    "reset_registry",
]
