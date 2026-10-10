"""Accepted permission prompts → candidate Policy entries (PAP-4, GH-801).

The friction flows (worktree→main sync, auto-gate persistence, the
promote path) all turn an observed rule string into a catalog entry.
Before PAP-4 that transition was stringly-typed — the rule's origin and
review status vanished at the moment of persistence. This seam keeps
them: an accepted prompt becomes a :class:`Policy` with
``lifecycle=candidate``, carrying who authored it (source tier) and why
(rationale), so downstream curation can distinguish a reviewed catalog
rule from a session artifact.
"""

from __future__ import annotations

from dev10x.domain.common.policy import Policy, PolicyEffect, PolicyLifecycle, PolicySource

CANDIDATE_TIER = 3


def policy_from_accepted_prompt(
    *,
    rule: str,
    source: PolicySource,
    rationale: str = "",
) -> Policy:
    """Wrap an accepted prompt's rule string as a candidate Policy."""
    return Policy.from_rule_str(
        rule,
        tier=CANDIDATE_TIER,
        source=source,
        effect=PolicyEffect.ALLOW,
        id=rule,
        rationale=rationale,
        lifecycle=PolicyLifecycle.CANDIDATE,
    )


__all__ = ["CANDIDATE_TIER", "policy_from_accepted_prompt"]
