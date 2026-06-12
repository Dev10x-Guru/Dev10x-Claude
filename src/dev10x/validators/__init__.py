"""Bash command validators for Claude Code PreToolUse hooks.

Single-dispatcher architecture: one Python process validates all Bash
commands by iterating a :class:`ValidatorRegistry`. Each validator
declares its profile tier and rule_id as class attributes (see
:mod:`dev10x.validators.base`); correction support is detected
structurally via the :class:`Corrector` protocol.

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

import functools
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
    ValidatorSpec(
        module_path="dev10x.validators.sensitivity_target",
        class_name="SensitivityTargetValidator",
        rule_id="DX014",
        profile=ProfileTier.STANDARD,
    ),
    ValidatorSpec(
        module_path="dev10x.validators.spec_drift",
        class_name="SpecDriftValidator",
        rule_id="DX015",
        profile=ProfileTier.STANDARD,
        experimental=True,
    ),
    ValidatorSpec(
        module_path="dev10x.validators.inline_linter",
        class_name="InlineLinterValidator",
        rule_id="DX016",
        profile=ProfileTier.STANDARD,
    ),
]


def _parse_profile_config(
    *, profile_raw: str | None, disable_raw: str, experimental_raw: str
) -> tuple[ProfileTier, set[str], bool]:
    """Parse raw env-var strings into a profile configuration tuple."""
    active = ProfileTier.from_raw(profile_raw)
    disabled = {rid.strip().upper() for rid in disable_raw.split(",") if rid.strip()}
    experimental = experimental_raw.strip().lower() in ("1", "true", "yes", "on")
    return active, disabled, experimental


def _load_profile_config() -> tuple[ProfileTier, set[str], bool]:
    """Read profile configuration from environment variables.

    Returns:
        (active_profile, disabled_rule_ids, experimental_enabled)
    """
    return _parse_profile_config(
        profile_raw=os.environ.get("DEV10X_HOOK_PROFILE"),
        disable_raw=os.environ.get("DEV10X_HOOK_DISABLE", ""),
        experimental_raw=os.environ.get("DEV10X_HOOK_EXPERIMENTAL", ""),
    )


@functools.cache
def _cached_registry(
    profile_raw: str | None, disable_raw: str, experimental_raw: str
) -> ValidatorRegistry:
    """Build the registry for one exact environment configuration (A10).

    Keyed on the raw env-var strings rather than stored in a
    process-wide ``_registry`` global, so changing the profile,
    disable-list, or experimental flag yields a distinct registry
    instead of silently reusing a stale singleton. Repeated calls with
    the same configuration return the same instance, preserving the
    lazy ``_instances`` caching inside :class:`ValidatorRegistry`.
    """
    active, disabled, experimental = _parse_profile_config(
        profile_raw=profile_raw,
        disable_raw=disable_raw,
        experimental_raw=experimental_raw,
    )
    return ValidatorRegistry(
        specs=list(_SPECS),
        filters=[
            ProfileFilter(active=active),
            DisableListFilter(disabled=frozenset(disabled)),
            ExperimentalFilter(enabled=experimental),
        ],
    )


def get_registry() -> ValidatorRegistry:
    """Return the registry for the current environment (cached per config)."""
    return _cached_registry(
        os.environ.get("DEV10X_HOOK_PROFILE"),
        os.environ.get("DEV10X_HOOK_DISABLE", ""),
        os.environ.get("DEV10X_HOOK_EXPERIMENTAL", ""),
    )


def get_validators() -> list[Validator]:
    """Return active validator instances (lazy-loaded on first call)."""
    return get_registry().active()


def reset_registry() -> None:
    """Clear the cached validator registries — used by tests."""
    _cached_registry.cache_clear()


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
