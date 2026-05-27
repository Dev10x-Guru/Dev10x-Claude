"""Backwards-compatible facade for the decomposed session modules (GH-144).

The original ``hooks/session.py`` mixed Event dispatch, Document
persistence, Rule/Policy, and Place provisioning. It has been split
into archetype-aligned modules:

* :mod:`dev10x.hooks.session_dispatch` — event routing.
* :mod:`dev10x.domain.session_document` — Document I/O.
* :mod:`dev10x.hooks.session_policy` — named Rule objects.
* :mod:`dev10x.hooks.session_place` — Place provisioning.
* :mod:`dev10x.session.queries` — aggregated SessionContextQuery.

This module re-exports the public surface that
``hooks/scripts/session-*.py``, ``commands/hook.py``, and the test
suite import. Prefer importing from the new modules in new code.
"""

from __future__ import annotations

from dev10x.domain.session_document import (
    claim_state_file as _claim_state_file,
)
from dev10x.domain.session_document import (
    read_json as _read_json,
)
from dev10x.hooks.session_dispatch import (
    build_autonomy_reassurance_context,  # noqa: F401 — re-exported via __all__
    build_guidance_context,  # noqa: F401 — re-exported via __all__
    build_install_check_context,  # noqa: F401 — re-exported via __all__
    build_reload_context,  # noqa: F401 — re-exported via __all__
    context_compact,  # noqa: F401 — re-exported via __all__
    session_goodbye,  # noqa: F401 — re-exported via __all__
    session_guidance,  # noqa: F401 — re-exported via __all__
    session_install_check,  # noqa: F401 — re-exported via __all__
    session_migrate_permissions,  # noqa: F401 — re-exported via __all__
    session_persist,  # noqa: F401 — re-exported via __all__
    session_reload,  # noqa: F401 — re-exported via __all__
)
from dev10x.hooks.session_place import session_git_aliases, session_tmpdir
from dev10x.hooks.session_policy import (
    DecisionGuidanceRule,
    ReadFrictionLevelRule,
    _build_migration_replacements,
    _deduplicate_rules,
    _migrate_rules,
)


def _format_session_state(*, state):
    """Compatibility shim — prefer ``SessionState.from_dict(...).format_for_display()``."""
    from dev10x.domain.documents.session_state import SessionState

    return SessionState.from_dict(data=state).format_for_display()


def _format_plan_summary(*, plan):
    """Compatibility shim — prefer ``PlanSummary.from_dict(...).format_for_display()``."""
    from dev10x.domain.documents.session_state import PlanSummary

    return PlanSummary.from_dict(data=plan).format_for_display()


def _read_friction_level(*, toplevel: str):
    """Compatibility shim — prefer ``ReadFrictionLevelRule(toplevel=...).apply()``."""
    return ReadFrictionLevelRule(toplevel=toplevel).apply()


def _format_decision_guidance(*, plan, friction_level):
    """Compatibility shim — prefer ``DecisionGuidanceRule(...).apply()``."""
    return DecisionGuidanceRule(plan=plan, friction_level=friction_level).apply()


__all__ = [
    "build_autonomy_reassurance_context",
    "build_guidance_context",
    "build_install_check_context",
    "build_reload_context",
    "context_compact",
    "session_git_aliases",
    "session_goodbye",
    "session_guidance",
    "session_install_check",
    "session_migrate_permissions",
    "session_persist",
    "session_reload",
    "session_tmpdir",
    "_build_migration_replacements",
    "_claim_state_file",
    "_deduplicate_rules",
    "_format_decision_guidance",
    "_format_plan_summary",
    "_format_session_state",
    "_migrate_rules",
    "_read_friction_level",
    "_read_json",
]
