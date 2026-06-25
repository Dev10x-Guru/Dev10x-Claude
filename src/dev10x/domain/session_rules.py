"""Session policy rules — pure decisions owned by the domain core.

These were previously defined in ``dev10x.hooks.session_policy``, which
forced ``domain.documents.session_context`` to defer its imports into
function bodies to break the cycle ``hooks.session_dispatch →
domain.documents.session_context → hooks.session_policy`` (audit memo
Findings I2 + I10). Each rule depends only on ``domain/`` types, so it
belongs in the core: adapters now import them inward instead of reaching
up into ``hooks/``.

All rules here are free of file I/O (ADR-0007 D3). The session.yaml read
is owned by :class:`dev10x.domain.documents.session_yaml.SessionYamlDocument`;
callers read the parsed values there and pass them in as frozen fields.

See ADR-0008 (context boundary protocol) for the dependency-direction
rule and ADR-0007 for the Policy Rule archetype these satisfy.
"""

from __future__ import annotations

from dataclasses import dataclass

from dev10x.domain.documents.session_state import PlanSummary
from dev10x.domain.friction_level import FrictionLevel
from dev10x.domain.rules.policy_rule import PolicyRule


class UnknownFrictionLevelError(ValueError):
    """Raised when decision guidance is asked to format an unknown friction level."""


AUTO_PLAN_MODE = "auto-plan"
SOLO_MAINTAINER_MODE = "solo-maintainer"


def plan_gate_auto_approves(
    *,
    friction_level: FrictionLevel,
    active_modes: list[str],
) -> bool:
    """Decide whether the work-on Phase 3 plan-approval gate auto-resolves.

    Single source of truth for the GH-678 reconciliation: the plan gate
    auto-approves (the agent proceeds without presenting the approval
    widget) when EITHER

    * ``auto-plan`` is an active mode — the supervisor trusts the plan but
      keeps downstream decision gates firing per ``friction_level``; or
    * the long-standing ``adaptive`` + ``solo-maintainer`` profile is in
      effect (GH-252), where the friction profile already resolves to a
      clear default.

    Returns ``False`` for every other combination — notably ``adaptive``
    *without* ``solo-maintainer``, where the gate still emits its widget to
    preserve the supervisor's veto (it merely auto-selects the recommended
    option). This boolean is specifically "skip the widget", not "auto-pick
    once shown".
    """
    if AUTO_PLAN_MODE in active_modes:
        return True
    return friction_level is FrictionLevel.ADAPTIVE and SOLO_MAINTAINER_MODE in active_modes


@dataclass(frozen=True)
class DecisionGuidanceRule(PolicyRule[str]):
    """Format resume guidance for the agent based on plan + friction level.

    Raises ``UnknownFrictionLevelError`` when ``friction_level`` is not
    a recognised :class:`FrictionLevel` member. Audit M7 #D2 calls out
    the prior fall-through (which silently produced strict-style guidance
    for adaptive sessions) as a latent bug.
    """

    plan: PlanSummary
    friction_level: FrictionLevel

    def apply(self) -> str:
        if not isinstance(self.friction_level, FrictionLevel):
            raise UnknownFrictionLevelError(f"Unknown friction level: {self.friction_level!r}")

        if not self.plan.pending_decisions:
            if self.plan.has_remaining_tasks:
                return "Session resumed with tasks remaining. Auto-advance through the task list."
            return ""

        return self.friction_level.pending_decisions_guidance()


@dataclass(frozen=True)
class BuildAutonomyReassuranceRule(PolicyRule[str]):
    """Build a reassurance block for autonomous sessions (GH-261).

    Fires only when ``friction_level`` is ``ADAPTIVE`` AND
    ``solo-maintainer`` is among ``active_modes``. Reassures the agent
    that long task lists are by design and that re-asking settled scope
    decisions is the drift mode the supervisor explicitly opted out of.

    Returns an empty string outside the autonomous-shipping profile so
    the SessionStart orchestrator can drop the segment silently.

    The caller reads ``friction_level`` and ``active_modes`` from
    :class:`dev10x.domain.documents.session_yaml.SessionYamlDocument` and
    passes them in as frozen fields — the rule performs no file I/O
    (ADR-0007 D3). Relocated from ``hooks/session_policy.py`` to its
    archetype home in ``domain/`` once the I/O was removed (GH-524).
    """

    friction_level: FrictionLevel
    active_modes: list[str]

    REASSURANCE_TEXT = (
        "**Supervisor monitors context.** Long task lists are by design — "
        "the work-on skill creates one task per play step so the supervisor "
        'sees scope upfront. Do NOT pause to ask "should I proceed?" when:\n'
        "\n"
        "- The user already answered a scope AskUserQuestion\n"
        "- friction_level: adaptive is set (auto-advance is the contract)\n"
        "- The skill instructions explicitly cover the next step\n"
        "\n"
        "If context truly becomes a problem, the supervisor will interrupt. "
        "Context anxiety is the agent's drift mode — trust the plan."
    )

    def apply(self) -> str:
        if self.friction_level is not FrictionLevel.ADAPTIVE:
            return ""
        if "solo-maintainer" not in self.active_modes:
            return ""
        return self.REASSURANCE_TEXT


@dataclass(frozen=True)
class BuildAutoPlanGuidanceRule(PolicyRule[str]):
    """Build a SessionStart briefing for ``auto-plan`` sessions (GH-678).

    Fires only when ``auto-plan`` is among ``active_modes``. Reinforces the
    half of the contract that survives compaction least well: the
    plan-approval gate auto-resolved, but downstream decision gates still
    fire per ``friction_level`` and MUST NOT be skipped. Without this, a
    resumed/compacted session can over-generalise "the plan auto-approved"
    into "auto-advance through every gate".

    Returns an empty string outside ``auto-plan`` so the SessionStart
    orchestrator drops the segment silently. The caller reads
    ``friction_level`` and ``active_modes`` from
    :class:`dev10x.domain.documents.session_yaml.SessionYamlDocument` and
    passes them in as frozen fields — the rule performs no file I/O
    (ADR-0007 D3).
    """

    friction_level: FrictionLevel
    active_modes: list[str]

    GUIDANCE_TEXT = (
        "**`auto-plan` mode active.** The work-on plan-approval gate "
        "auto-resolves — start executing the plan without presenting it for "
        "approval. This is scoped to the plan gate ONLY:\n"
        "\n"
        "- Downstream decision gates (design forks, A/B choices, strategy "
        "selection) STILL fire per `friction_level` — do NOT skip them.\n"
        "- `ALWAYS_ASK` gates (destructive/irreversible ops) fire unchanged.\n"
        "- The Plan Completion Gate still fires for end-state sign-off.\n"
        "\n"
        'In short: "trust the plan — start; wake me for the judgment calls."'
    )

    def apply(self) -> str:
        if AUTO_PLAN_MODE not in self.active_modes:
            return ""
        return self.GUIDANCE_TEXT


__all__ = [
    "UnknownFrictionLevelError",
    "DecisionGuidanceRule",
    "BuildAutonomyReassuranceRule",
    "BuildAutoPlanGuidanceRule",
    "plan_gate_auto_approves",
    "AUTO_PLAN_MODE",
    "SOLO_MAINTAINER_MODE",
]
