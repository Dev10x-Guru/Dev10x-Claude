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

import enum
from dataclasses import dataclass

from dev10x.domain.documents.session_state import PlanSummary
from dev10x.domain.friction_level import FrictionLevel
from dev10x.domain.gate_policy import legacy_session_mapping
from dev10x.domain.rules.policy_rule import PolicyRule


class UnknownFrictionLevelError(ValueError):
    """Raised when decision guidance is asked to format an unknown friction level."""


AUTO_PLAN_MODE = "auto-plan"
SOLO_MAINTAINER_MODE = "solo-maintainer"


# The plan-approval gate decision moved into the gate-policy resolver
# (GH-755, ADR-0016 Phase 2): work-on resolves it via the ``plan_approval``
# toggle of :func:`dev10x.domain.gate_policy.resolve_gate` (exposed as the
# ``resolve_gate`` MCP tool) instead of a standalone predicate. The
# ``auto-plan`` and ``adaptive``+``solo-maintainer`` shapes the former
# ``plan_gate_auto_approves`` covered are now encoded in the shipped presets
# and the ``solo-maintainer`` overlay.


class CompletionRecommendation(enum.Enum):
    """The session-completion gate's recommended action (GH-729).

    Mirrors the canonical-rule pattern of the gate-policy resolver: the
    decision is encoded once here so verify-acc-dod's markdown,
    work-on's Plan Completion Gate, and any future consumer defer to it
    rather than re-deriving the matrix.
    """

    WORK_COMPLETE = "work_complete"
    MONITOR_REVIEW = "monitor_review"
    GO_BACK = "go_back"


def completion_gate_recommendation(
    *,
    has_associated_pr: bool,
    pr_merged: bool,
    blocking_checks_pass: bool,
) -> CompletionRecommendation:
    """Decide what the verify-acc-dod completion gate recommends (GH-729).

    Completion is reserved for the *merged* state: "shippable / handed
    off" is not terminal. The recommendation is friction-agnostic — the
    friction level governs only whether the gate fires as a widget or
    auto-selects this recommendation; it never changes which option is
    recommended.

    * ``blocking_checks_pass is False`` → :attr:`CompletionRecommendation.GO_BACK`.
      A real failure (CI red, unresolved review threads, dirty tree,
      draft PR) must be resolved first. The PR-merge signal is
      deliberately *not* one of these checks — an unmerged-but-otherwise
      -green PR is the normal awaiting-review state, and treating it as a
      blocking failure would loop forever (you cannot merge without
      review).
    * No associated PR (``investigation`` / ``local-only``) or the PR is
      merged → :attr:`CompletionRecommendation.WORK_COMPLETE`.
    * Otherwise the PR is open and otherwise-green →
      :attr:`CompletionRecommendation.MONITOR_REVIEW`: keep the session
      open and background-watch the PR for review / ready-to-merge via
      ``Dev10x:gh-pr-monitor``.
    """
    if not blocking_checks_pass:
        return CompletionRecommendation.GO_BACK
    if not has_associated_pr or pr_merged:
        return CompletionRecommendation.WORK_COMPLETE
    return CompletionRecommendation.MONITOR_REVIEW


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


@dataclass(frozen=True)
class ModeGuardRule(PolicyRule[str]):
    """Warn when a durable high-autonomy overlay is forbidden by repo policy (GH-805).

    Fires when the repo declares an ``allowed_overlays`` allow-list (in the
    gitignored, worktree-copied ``config.yaml``) and the durable session
    config would produce an overlay outside it — the classic case being a
    stale ``active_modes: [solo-maintainer]`` copied worktree-wide into a team
    repo. The resolver already *drops* that overlay before gate resolution;
    this rule makes the drop visible so a present supervisor sees the guard
    acted and can fix the config if it was intentional.

    Returns ``""`` when no allow-list is declared (``allowed_overlays is
    None``) or nothing would be dropped, so the SessionStart orchestrator
    drops the segment silently. I/O-free (ADR-0007 D3): the caller reads
    ``active_modes`` / ``walk_away`` / ``allowed_overlays`` from
    :class:`dev10x.domain.documents.session_yaml.SessionYamlDocument` and
    passes them in as frozen fields.
    """

    active_modes: list[str]
    walk_away: bool
    allowed_overlays: list[str] | None

    def apply(self) -> str:
        if self.allowed_overlays is None:
            return ""
        # friction_level is irrelevant to overlay derivation — reuse the
        # resolver's own mapping so the warning names exactly the overlays the
        # boundary drops (no second, drifting derivation of the mode→overlay map).
        _, overlays = legacy_session_mapping(
            friction_level="guided",
            active_modes=self.active_modes,
            walk_away=self.walk_away,
        )
        dropped = [overlay for overlay in overlays if overlay not in self.allowed_overlays]
        if not dropped:
            return ""
        names = ", ".join(dropped)
        return (
            f"**⚠ Durable-mode guard (GH-805).** This repo's `allowed_overlays` "
            f"policy does not permit: {names}. That high-autonomy overlay is being "
            "dropped before every gate resolution this session — request-review, "
            "external-notify, and merge stay human-driven regardless of the durable "
            "`active_modes` in config.yaml. If this is intentional, edit "
            "`.claude/Dev10x/config.yaml` (`active_modes` or `allowed_overlays`)."
        )


__all__ = [
    "UnknownFrictionLevelError",
    "DecisionGuidanceRule",
    "BuildAutonomyReassuranceRule",
    "BuildAutoPlanGuidanceRule",
    "ModeGuardRule",
    "CompletionRecommendation",
    "completion_gate_recommendation",
    "AUTO_PLAN_MODE",
    "SOLO_MAINTAINER_MODE",
]
