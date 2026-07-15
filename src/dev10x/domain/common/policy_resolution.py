"""Policy precedence engine (PAP-1, GH-798).

Resolves the effect a layered policy set expresses for one tool-call
signature. Three source tiers participate, highest precedence first:

1. ``project-local`` — rules in the repo's own settings
2. ``user-private`` — the synced user catalog
3. ``plugin-default`` — the shipped baseline

Two rules govern resolution:

- **Forbid-wins** — a matching ``deny`` at ANY tier decides the outcome,
  regardless of precedence. A project cannot allow what the plugin
  baseline forbids, and vice versa.
- **Highest tier decides otherwise** — among non-deny matches, the
  highest-precedence source owns the decision; within that source the
  more restrictive effect wins (``ask`` beats ``allow``).

Disabled and deprecated policies never participate
(:attr:`Policy.is_effective`). No match resolves to ``None`` — the
caller owns the no-decision fallback, mirroring how the shipped
settings files leave unmatched signatures to the harness prompt.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from pathlib import Path

from dev10x.domain.common.baseline_catalog import load_baseline_dict
from dev10x.domain.common.policy import (
    Policy,
    PolicyAssessment,
    PolicyCatalog,
    PolicyEffect,
    PolicySource,
)
from dev10x.domain.common.policy_migration import migrate_flat_config

PRECEDENCE: tuple[PolicySource, ...] = (
    PolicySource.PROJECT_LOCAL,
    PolicySource.USER_PRIVATE,
    PolicySource.PLUGIN_DEFAULT,
)


def resolve_effect(
    *,
    policies: Iterable[Policy],
    signature: str,
    context: str = "",
) -> PolicyEffect | None:
    """Resolve the layered effect for ``signature``; ``None`` when unmatched.

    ``context`` is the active skill context (PAP-5, GH-802): a policy
    whose ``scope.context`` is set participates only when the invocation
    context matches it; unscoped policies always participate.
    """
    matches = [
        policy
        for policy in policies
        if policy.is_effective
        and _in_context(policy=policy, context=context)
        and policy.matches(signature=signature)
    ]
    if not matches:
        return None
    if any(policy.effect is PolicyEffect.DENY for policy in matches):
        return PolicyEffect.DENY
    for source in PRECEDENCE:
        effects = {policy.effect for policy in matches if policy.source is source}
        if not effects:
            continue
        if PolicyEffect.ASK in effects:
            return PolicyEffect.ASK
        return PolicyEffect.ALLOW
    return None


def _in_context(*, policy: Policy, context: str) -> bool:
    return policy.scope.context in ("", context)


def attach_assessments(
    *,
    policies: Iterable[Policy],
    records: dict[str, tuple[PolicyAssessment, ...]],
) -> list[Policy]:
    """Attach investigator/auditor records to their policies (PAP-5).

    ``records`` maps a policy signature to the assessments recorded for
    it. Policies without records pass through unchanged; existing
    assessments are preserved and extended.
    """
    attached: list[Policy] = []
    for policy in policies:
        extra = records.get(policy.signature)
        if not extra:
            attached.append(policy)
            continue
        attached.append(dataclasses.replace(policy, assessments=policy.assessments + tuple(extra)))
    return attached


def load_policy_layers(
    *,
    plugin_path: str | Path | None = None,
    user_path: str | Path | None = None,
    project_path: str | Path | None = None,
) -> list[Policy]:
    """Load up to three catalog files into one tagged policy set.

    Each layer may be either the grouped ``baseline-permissions.yaml``
    shape or a flat ``base_permissions``/``base_denies`` config (GH-819).
    A flat layer is normalized through :func:`migrate_flat_config` and
    re-tagged with this layer's :class:`PolicySource` so it participates
    in resolution instead of silently contributing nothing. Missing or
    malformed files still contribute nothing (mirroring
    :meth:`PolicyCatalog.load`), so a partial installation still resolves
    against the layers it has.
    """
    layers: list[tuple[str | Path | None, PolicySource]] = [
        (plugin_path, PolicySource.PLUGIN_DEFAULT),
        (user_path, PolicySource.USER_PRIVATE),
        (project_path, PolicySource.PROJECT_LOCAL),
    ]
    policies: list[Policy] = []
    for path, source in layers:
        if path is None:
            continue
        policies.extend(_load_layer(path=path, source=source))
    return policies


def _load_layer(*, path: str | Path, source: PolicySource) -> list[Policy]:
    data = load_baseline_dict(Path(path), strict=False)
    if not data:
        return []
    if not _is_flat_shape(data=data):
        return PolicyCatalog.from_baseline_dict(data, source=source)
    migrated = migrate_flat_config(config=data)
    if source is PolicySource.PLUGIN_DEFAULT:
        return migrated
    return [dataclasses.replace(policy, source=source) for policy in migrated]


def _is_flat_shape(*, data: dict) -> bool:
    """Detect the PAP-2 flat shape vs the grouped structured catalog.

    Structured catalogs key their rules under ``groups``; flat configs
    (``projects.yaml``-style) carry bare ``base_permissions``/
    ``base_denies`` lists instead. A layer carrying a ``groups`` mapping
    is treated as structured even if it also has flat-looking keys, so
    an already-migrated layer is never double-migrated.
    """
    if isinstance(data.get("groups"), dict):
        return False
    return isinstance(data.get("base_permissions"), list) or isinstance(
        data.get("base_denies"), list
    )


__all__ = ["PRECEDENCE", "attach_assessments", "load_policy_layers", "resolve_effect"]
