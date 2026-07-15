"""Flat base_permissions catalog → structured Policy entries (PAP-2, GH-799).

The core migration logic (:func:`migrate_flat_config` and its pure
helpers) lives in :mod:`dev10x.domain.common.policy_migration` — moved
there in GH-819 so ``domain/`` code (``policy_resolution.py``) never
imports from the ``skills/`` adapter layer (ADR-0008). This module
re-exports those symbols for backward compatibility with existing
skills-layer importers, and keeps the PAP-2 compatibility shim
(``flat_allow_rules``/``flat_deny_rules``) that projects a policy set
back to the exact flat lists so ``ensure_base`` renders byte-identical
settings output until the PAP-3 renderer replaces it.
"""

from __future__ import annotations

from dev10x.domain.common.policy import Policy, PolicyEffect
from dev10x.domain.common.policy_migration import (
    BASELINE_CATALOG_PATH,
    CLAUDE_AI_MCP_GROUP,
    DEFAULT_TIER,
    FENCE_TOOL_PROBE_GROUP,
    load_baseline_policies,
    migrate_flat_config,
)


def flat_allow_rules(*, policies: list[Policy]) -> list[str]:
    """Project allow policies back to the flat ``base_permissions`` list."""
    return [p.signature for p in policies if p.effect is PolicyEffect.ALLOW]


def flat_deny_rules(*, policies: list[Policy]) -> list[str]:
    """Project deny policies back to the flat ``base_denies`` list."""
    return [p.signature for p in policies if p.effect is PolicyEffect.DENY]


__all__ = [
    "BASELINE_CATALOG_PATH",
    "CLAUDE_AI_MCP_GROUP",
    "DEFAULT_TIER",
    "FENCE_TOOL_PROBE_GROUP",
    "flat_allow_rules",
    "flat_deny_rules",
    "load_baseline_policies",
    "migrate_flat_config",
]
