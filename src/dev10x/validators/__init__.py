"""Bash command validators for Claude Code PreToolUse hooks.

Single-dispatcher architecture: one Python process validates all Bash
commands by iterating a :class:`ValidatorRegistry`. Each validator
declares its profile tier, rule_id, and capabilities as class
attributes (see :mod:`dev10x.validators.base`).

Ordering matters: allow-validators run before deny-validators so safe
patterns get auto-approved before a deny-validator would block them.

Validators are lazily imported — the registry only loads modules for
specs surviving the active filter set. This avoids paying the import
cost of all 8 modules at module-level on every hook invocation.

Profile filtering (GH-413): each :class:`ValidatorSpec` carries a
:class:`ProfileTier` and a rule_id. The registry composes three
filters built from environment variables:

  DEV10X_HOOK_PROFILE        — active tier (default ``STANDARD``)
  DEV10X_HOOK_DISABLE        — comma-separated rule_ids to drop
  DEV10X_HOOK_EXPERIMENTAL   — opt-in flag for experimental validators
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from dev10x.domain.profile_tier import ProfileTier
from dev10x.validators.registry import (
    DisableListFilter,
    ExperimentalFilter,
    ProfileFilter,
    ValidatorChain,
    ValidatorRegistry,
    ValidatorSpec,
)

if TYPE_CHECKING:
    from dev10x.validators.base import Validator

_SPECS: list[ValidatorSpec] = [
    ValidatorSpec(
        module_path="dev10x.validators.safe_subshell",
        class_name="SafeSubshellValidator",
        rule_id="DX001",
        profile=ProfileTier.MINIMAL,
    ),
    ValidatorSpec(
        module_path="dev10x.validators.command_substitution",
        class_name="CommandSubstitutionValidator",
        rule_id="DX002",
        profile=ProfileTier.MINIMAL,
    ),
    ValidatorSpec(
        module_path="dev10x.validators.execution_safety",
        class_name="ExecutionSafetyValidator",
        rule_id="DX003",
        profile=ProfileTier.MINIMAL,
    ),
    ValidatorSpec(
        module_path="dev10x.validators.sql_safety",
        class_name="SqlSafetyValidator",
        rule_id="DX004",
        profile=ProfileTier.MINIMAL,
    ),
    ValidatorSpec(
        module_path="dev10x.validators.pr_base",
        class_name="PrBaseValidator",
        rule_id="DX005",
        profile=ProfileTier.MINIMAL,
    ),
    ValidatorSpec(
        module_path="dev10x.validators.pipeline_allow",
        class_name="PipelineAllowValidator",
        rule_id="DX011",
        profile=ProfileTier.STANDARD,
    ),
    ValidatorSpec(
        module_path="dev10x.validators.skill_redirect",
        class_name="SkillRedirectValidator",
        rule_id="DX006",
        profile=ProfileTier.STANDARD,
    ),
    ValidatorSpec(
        module_path="dev10x.validators.prefix_friction",
        class_name="PrefixFrictionValidator",
        rule_id="DX007",
        profile=ProfileTier.STANDARD,
    ),
    ValidatorSpec(
        module_path="dev10x.validators.mcp_prefix",
        class_name="McpPrefixValidator",
        rule_id="DX013",
        profile=ProfileTier.STANDARD,
    ),
    ValidatorSpec(
        module_path="dev10x.validators.commit_jtbd",
        class_name="CommitJtbdValidator",
        rule_id="DX008",
        profile=ProfileTier.STRICT,
    ),
    ValidatorSpec(
        module_path="dev10x.validators.redundant_fetch",
        class_name="RedundantFetchValidator",
        rule_id="DX009",
        profile=ProfileTier.STANDARD,
        experimental=True,
    ),
    ValidatorSpec(
        module_path="dev10x.validators.bash_aggregation",
        class_name="BashAggregationValidator",
        rule_id="DX010",
        profile=ProfileTier.STANDARD,
    ),
    ValidatorSpec(
        module_path="dev10x.validators.safe_expansion",
        class_name="SafeExpansionValidator",
        rule_id="DX012",
        profile=ProfileTier.MINIMAL,
    ),
]


def _load_profile_config() -> tuple[ProfileTier, set[str], bool]:
    """Read profile configuration from environment variables.

    Returns:
        (active_profile, disabled_rule_ids, experimental_enabled)
    """
    active = ProfileTier.from_raw(os.environ.get("DEV10X_HOOK_PROFILE"))

    disabled_raw = os.environ.get("DEV10X_HOOK_DISABLE", "")
    disabled = {rid.strip().upper() for rid in disabled_raw.split(",") if rid.strip()}

    experimental_raw = os.environ.get("DEV10X_HOOK_EXPERIMENTAL", "").strip().lower()
    experimental_enabled = experimental_raw in ("1", "true", "yes", "on")

    return active, disabled, experimental_enabled


def _build_registry() -> ValidatorRegistry:
    """Construct a registry seeded with module specs and env-driven filters."""
    active, disabled, experimental = _load_profile_config()
    return ValidatorRegistry(
        specs=list(_SPECS),
        filters=[
            ProfileFilter(active=active),
            DisableListFilter(disabled=frozenset(disabled)),
            ExperimentalFilter(enabled=experimental),
        ],
    )


_registry: ValidatorRegistry | None = None


def get_registry() -> ValidatorRegistry:
    """Return the process-wide registry, building it on first access."""
    global _registry
    if _registry is None:
        _registry = _build_registry()
    return _registry


def get_validators() -> list[Validator]:
    """Return active validator instances (lazy-loaded on first call)."""
    return get_registry().active()


def reset_registry() -> None:
    """Clear the cached validator registry — used by tests."""
    global _registry
    _registry = None


def get_chain() -> ValidatorChain:
    """Return a chain bound to the process-wide registry."""
    return ValidatorChain(registry=get_registry())


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
