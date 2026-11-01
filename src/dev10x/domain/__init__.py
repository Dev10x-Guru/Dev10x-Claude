"""Re-export of ``dev10x.core.domain`` at its pre-ADR-0034 path (GH-1533).

Every ``dev10x.domain.<name>`` resolves to the same module object as
``dev10x.core.domain.<name>``; see ``dev10x.core.module_alias``.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_package

if TYPE_CHECKING:
    from dev10x.core.domain import (
        Compensation,
        Config,
        ConfigLoader,
        ErrorResult,
        GitContext,
        HookAllow,
        HookAsk,
        HookHint,
        HookInput,
        HookResult,
        HookRetry,
        MatchingRule,
        Plan,
        RepositoryRef,
        Result,
        RuleEngine,
        RuleMatch,
        SensitivityClassifier,
        SensitivityLabel,
        SensitivityMatch,
        SqlStatement,
        SuccessResult,
        err,
        is_read_only_sql,
        ok,
    )

alias_package(old=__name__, new="dev10x.core.domain")

__all__ = [
    "Compensation",
    "Config",
    "ConfigLoader",
    "ErrorResult",
    "GitContext",
    "HookAllow",
    "HookAsk",
    "HookHint",
    "HookInput",
    "HookResult",
    "HookRetry",
    "MatchingRule",
    "Plan",
    "RepositoryRef",
    "Result",
    "RuleEngine",
    "RuleMatch",
    "SensitivityClassifier",
    "SensitivityLabel",
    "SensitivityMatch",
    "SqlStatement",
    "SuccessResult",
    "err",
    "is_read_only_sql",
    "ok",
]
