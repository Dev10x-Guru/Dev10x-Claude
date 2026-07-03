"""Gate policy resolver — presets over toggles (ADR-0016 spike).

Single source of truth for "does this decision gate fire or
auto-resolve?". Skills are policy-ignorant: they call the
``resolve_gate`` MCP tool (which delegates here) instead of reading
``friction_level`` / ``active_modes`` / ``walk_away`` and re-deriving
gate behavior from prose.

Resolution pipeline (ADR-0016 D-4, lowest to highest precedence):

    plugin preset < project override < session preset choice
                  < per-toggle session override < safety floors

All functions are free of file I/O (ADR-0007 D3): the caller reads
session/project configuration and passes parsed values in. Shipped
preset value-maps live here as data; the planned
``presets/friction/*.yaml`` files (ADR-0016 Q2) will hydrate the same
structures at the infra tier.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class GateEffect(enum.Enum):
    """How a gate resolves for the current session (ADR-0016 D-6)."""

    ASK = "ask"
    AUTO = "auto"
    SKIP = "skip"


class UnknownToggleError(ValueError):
    """Raised when a gate name does not map to a known toggle."""


class UnknownPresetError(ValueError):
    """Raised when a preset name is not shipped and not user-supplied."""


# Conditional toggle values — auto when the condition holds, else ask.
AUTO_IF_BOT = "auto_if_bot"
AUTO_IF_SAFE = "auto_if_safe"
AUTO_IF_MERGED = "auto_if_merged"
AUTO_IF_STALE_FREE = "auto_if_stale_free"

_ENUM_TOGGLES: frozenset[str] = frozenset(
    {
        "plan_approval",
        "batch_layout",
        "strategy_choice",
        "artifact_preview",
        "triage_response",
        "thread_resolution",
        "comment_hide",
        "yagni_routing",
        "shipping_continuation",
        "request_review",
        "external_notify",
        "merge",
        "completion_signoff",
        "history_rewrite",
        "workspace_choice",
        "branch_cleanup",
        "session_adoption",
    }
)

_WEIGHT_TOGGLES: frozenset[str] = frozenset({"autofix_confidence", "batch_ambiguity_floor"})

_BOOL_TOGGLES: frozenset[str] = frozenset({"zero_valid_autoflow", "anchor_recommendations"})

_SETTING_TOGGLES: frozenset[str] = frozenset({"doubt_sink"})

KNOWN_TOGGLES: frozenset[str] = _ENUM_TOGGLES | _WEIGHT_TOGGLES | _BOOL_TOGGLES | _SETTING_TOGGLES

# ADR-0016 "Shipped presets" table. A weight of NEVER_THRESHOLD means the
# weight-conditioned auto can never trigger; ALWAYS_ASK_SIGNALS likewise.
NEVER_THRESHOLD = 101
ALWAYS_ASK_SIGNALS = 10_000

SHIPPED_PRESETS: dict[str, dict[str, str | int | bool]] = {
    "strict": {
        **{toggle: "ask" for toggle in _ENUM_TOGGLES},
        "zero_valid_autoflow": False,
        "autofix_confidence": NEVER_THRESHOLD,
        "batch_ambiguity_floor": ALWAYS_ASK_SIGNALS,
        "anchor_recommendations": False,
        "doubt_sink": "pr-description",
    },
    "guided": {
        **{toggle: "ask" for toggle in _ENUM_TOGGLES},
        "session_adoption": AUTO_IF_STALE_FREE,
        "zero_valid_autoflow": False,
        "autofix_confidence": 70,
        "batch_ambiguity_floor": 3,
        "anchor_recommendations": True,
        "doubt_sink": "pr-description",
    },
    "adaptive": {
        "plan_approval": "auto",
        "batch_layout": "auto",
        "strategy_choice": "auto",
        "artifact_preview": "auto",
        "triage_response": AUTO_IF_BOT,
        "thread_resolution": AUTO_IF_BOT,
        "comment_hide": "auto",
        "yagni_routing": "auto",
        "shipping_continuation": "auto",
        "request_review": "auto",
        "external_notify": "ask",
        "merge": "auto",
        "completion_signoff": "auto",
        "history_rewrite": AUTO_IF_SAFE,
        "workspace_choice": "auto",
        "branch_cleanup": AUTO_IF_MERGED,
        "session_adoption": AUTO_IF_STALE_FREE,
        "zero_valid_autoflow": True,
        "autofix_confidence": 70,
        "batch_ambiguity_floor": 3,
        "anchor_recommendations": True,
        "doubt_sink": "pr-description",
    },
}

# Overlay presets — sparse patches applied on top of a base preset.
SHIPPED_OVERLAYS: dict[str, dict[str, str | int | bool]] = {
    "solo-maintainer": {
        "request_review": "skip",
        "external_notify": "skip",
        "merge": "auto",
    },
    "afk": {
        "session_adoption": "auto",
        "doubt_sink": "pr-description",
    },
}


@dataclass(frozen=True)
class GateContext:
    """Facts about the concrete gate instance, supplied by the skill.

    Every field is optional — an omitted fact resolves in the *safe*
    direction (unknown author is human, unknown reversibility is not
    provably safe, unknown staleness is stale).
    """

    author_type: str | None = None  # "bot" | "human" | None (= human)
    destructive: bool = False
    irreversible: bool = False
    cross_author: bool = False
    secret_access: bool = False
    privacy_disclosure: bool = False
    blocking: bool = False
    provably_safe: bool = False  # history_rewrite: fixup-only groom etc.
    branch_merged: bool = False  # branch_cleanup: tip reachable from base
    session_stale: bool = True  # session_adoption: yaml mismatches work
    overlap_signals: int | None = None
    confidence: int | None = None
    valid_fixup_count: int | None = None


@dataclass(frozen=True)
class GateResolution:
    """The resolver's answer for one gate instance (wire-shaped)."""

    gate: str
    effect: GateEffect
    resolved_option: str | None
    log_to: str
    reason: str
    floors_applied: list[str] = field(default_factory=list)
    anchor_recommendations: bool = True

    def to_payload(self) -> dict[str, object]:
        return {
            "gate": self.gate,
            "effect": self.effect.value,
            "resolved_option": self.resolved_option,
            "log_to": self.log_to,
            "reason": self.reason,
            "floors_applied": self.floors_applied,
            "anchor_recommendations": self.anchor_recommendations,
        }


def _floors(context: GateContext) -> list[str]:
    """Safety floors — deny-overrides; ``ask`` regardless of any toggle."""
    floors: list[str] = []
    if context.secret_access:
        floors.append("secret_access")
    if context.destructive and context.irreversible:
        floors.append("destructive_irreversible")
    if context.cross_author:
        floors.append("cross_author_push")
    if context.privacy_disclosure:
        floors.append("privacy_disclosure")
    if context.blocking:
        floors.append("blocking")
    return floors


def _merge_layers(
    *,
    preset: str,
    overlays: list[str],
    project_overrides: dict[str, str | int | bool],
    session_overrides: dict[str, str | int | bool],
    user_presets: dict[str, dict[str, str | int | bool]] | None = None,
) -> dict[str, str | int | bool]:
    presets = {**SHIPPED_PRESETS, **(user_presets or {})}
    if preset not in presets:
        raise UnknownPresetError(f"Unknown preset {preset!r}; shipped: {sorted(SHIPPED_PRESETS)}")
    resolved = dict(presets[preset])
    for overlay in overlays:
        if overlay not in SHIPPED_OVERLAYS:
            raise UnknownPresetError(
                f"Unknown overlay {overlay!r}; shipped: {sorted(SHIPPED_OVERLAYS)}"
            )
        resolved.update(SHIPPED_OVERLAYS[overlay])
    resolved.update(project_overrides)
    resolved.update(session_overrides)
    return resolved


def _apply_conditions(
    *, gate: str, value: str, context: GateContext, toggles: dict[str, str | int | bool]
) -> tuple[GateEffect, str]:
    """Resolve conditional enum values against the gate context."""
    if value == "skip":
        return GateEffect.SKIP, f"{gate}=skip"
    if value == "ask":
        return GateEffect.ASK, f"{gate}=ask"
    if value == AUTO_IF_BOT:
        author = context.author_type or "human"
        if author == "bot":
            return GateEffect.AUTO, f"{gate}={AUTO_IF_BOT} author=bot"
        return GateEffect.ASK, f"{gate}={AUTO_IF_BOT} author={author}"
    if value == AUTO_IF_SAFE:
        if context.provably_safe:
            return GateEffect.AUTO, f"{gate}={AUTO_IF_SAFE} safe=true"
        return GateEffect.ASK, f"{gate}={AUTO_IF_SAFE} safe=false"
    if value == AUTO_IF_MERGED:
        if context.branch_merged:
            return GateEffect.AUTO, f"{gate}={AUTO_IF_MERGED} merged=true"
        return GateEffect.ASK, f"{gate}={AUTO_IF_MERGED} merged=false"
    if value == AUTO_IF_STALE_FREE:
        if not context.session_stale:
            return GateEffect.AUTO, f"{gate}={AUTO_IF_STALE_FREE} stale=false"
        return GateEffect.ASK, f"{gate}={AUTO_IF_STALE_FREE} stale=true"
    if value == "auto":
        effect, reason = _weight_conditions(gate=gate, context=context, toggles=toggles)
        return effect, reason
    raise UnknownToggleError(f"Unknown value {value!r} for toggle {gate!r}")


def _weight_conditions(
    *, gate: str, context: GateContext, toggles: dict[str, str | int | bool]
) -> tuple[GateEffect, str]:
    """Weight toggles and the zero-VALID bool condition plain ``auto``."""
    if gate == "batch_layout" and context.overlap_signals is not None:
        floor = int(toggles["batch_ambiguity_floor"])
        if context.overlap_signals < floor:
            return (
                GateEffect.ASK,
                f"{gate}=auto signals={context.overlap_signals}<floor={floor}",
            )
        return (
            GateEffect.AUTO,
            f"{gate}=auto signals={context.overlap_signals}>=floor={floor}",
        )
    if (
        gate in {"triage_response", "thread_resolution", "comment_hide"}
        and context.valid_fixup_count == 0
        and not bool(toggles["zero_valid_autoflow"])
    ):
        return GateEffect.ASK, f"{gate}=auto zero_valid_autoflow=0"
    return GateEffect.AUTO, f"{gate}=auto"


def resolve_gate(
    *,
    gate: str,
    context: GateContext,
    preset: str,
    overlays: list[str] | None = None,
    project_overrides: dict[str, str | int | bool] | None = None,
    session_overrides: dict[str, str | int | bool] | None = None,
    user_presets: dict[str, dict[str, str | int | bool]] | None = None,
) -> GateResolution:
    """Resolve one decision gate to ask / auto / skip (ADR-0016).

    Pipeline: merge layers (preset → overlays → project → session
    per-toggle), evaluate conditional values against ``context``, then
    apply safety floors — floors always win (deny-overrides).
    """
    if gate not in _ENUM_TOGGLES:
        raise UnknownToggleError(f"Unknown gate {gate!r}; known: {sorted(_ENUM_TOGGLES)}")
    toggles = _merge_layers(
        preset=preset,
        overlays=list(overlays or []),
        project_overrides=dict(project_overrides or {}),
        session_overrides=dict(session_overrides or {}),
        user_presets=user_presets,
    )
    anchor = bool(toggles["anchor_recommendations"])
    log_to = str(toggles["doubt_sink"])

    floors = _floors(context)
    if floors:
        return GateResolution(
            gate=gate,
            effect=GateEffect.ASK,
            resolved_option=None,
            log_to=log_to,
            reason=f"floor:{'+'.join(floors)} overrides preset:{preset}",
            floors_applied=floors,
            anchor_recommendations=anchor,
        )

    value = str(toggles[gate])
    effect, reason = _apply_conditions(gate=gate, value=value, context=context, toggles=toggles)
    return GateResolution(
        gate=gate,
        effect=effect,
        resolved_option="Recommended" if effect is GateEffect.AUTO else None,
        log_to=log_to,
        reason=f"preset:{preset} {reason}",
        floors_applied=[],
        anchor_recommendations=anchor,
    )


def legacy_session_mapping(
    *,
    friction_level: str,
    active_modes: list[str],
    walk_away: bool,
) -> tuple[str, list[str]]:
    """Map a pre-ADR-0016 session.yaml shape to (preset, overlays).

    Read-compatibility seam: ``friction_level`` maps 1:1 to the shipped
    preset of the same name; ``solo-maintainer`` in ``active_modes`` maps
    to the solo-maintainer overlay; ``walk_away: true`` maps to the afk
    overlay. Structural modes (``review-deferred``, ``swarm-child``)
    stay in ``active_modes`` and are not gate concerns.
    """
    overlays: list[str] = []
    if "solo-maintainer" in active_modes:
        overlays.append("solo-maintainer")
    if walk_away:
        overlays.append("afk")
    return friction_level, overlays


__all__ = [
    "GateContext",
    "GateEffect",
    "GateResolution",
    "KNOWN_TOGGLES",
    "SHIPPED_OVERLAYS",
    "SHIPPED_PRESETS",
    "UnknownPresetError",
    "UnknownToggleError",
    "legacy_session_mapping",
    "resolve_gate",
]
