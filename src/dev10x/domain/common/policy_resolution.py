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

from dev10x.domain.common.policy import (
    Policy,
    PolicyAssessment,
    PolicyCatalog,
    PolicyEffect,
    PolicySource,
)

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
    """Load up to three existing-shape catalog files into one policy set.

    Each layer is the grouped ``baseline-permissions.yaml`` shape and is
    tagged with its :class:`PolicySource`. Missing or malformed files
    contribute nothing (mirroring :meth:`PolicyCatalog.load`), so a
    partial installation still resolves against the layers it has.
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
        policies.extend(PolicyCatalog.load(path, source=source))
    return policies


__all__ = ["PRECEDENCE", "attach_assessments", "load_policy_layers", "resolve_effect"]
