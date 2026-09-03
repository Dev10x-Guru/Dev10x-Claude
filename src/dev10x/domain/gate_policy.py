"""Gate policy resolver — presets over toggles (ADR-0016 spike).

Single source of truth for "does this decision gate fire or
auto-resolve?". Skills are policy-ignorant: they call the
``resolve_gate`` MCP tool (which delegates here) instead of reading
``friction_level`` / ``active_modes`` / ``walk_away`` and re-deriving
gate behavior from prose.

Resolution pipeline (ADR-0016 D-4, lowest to highest precedence):

    plugin preset < project override < session preset choice
                  < per-toggle session override < safety floors

Baseline posture (ADR-0022 D-1): ``adaptive`` is the **sole shipped
base preset** — auto-advance is the baseline, and every gate resolves
to its recommended option unless a floor, a project pin, or a
per-toggle override says otherwise. The ADR-0016 D-9 ``strict`` /
``guided`` columns are retired; the postures they reached for are now
expressed by ``supervisor_review`` (ADR-0022 D-2/D-3) and the existing
project-tier ``.dev10x/gate-policy.yaml`` pins.

The preset *mechanism* survives: user-defined presets in
``~/.config/Dev10x/friction-presets.yaml`` and per-toggle overrides
(ADR-0016 D-4) are untouched. Only the shipped three-way *choice* is
gone, so a config naming ``strict`` or ``guided`` now raises
:class:`UnknownPresetError` — loudly, rather than silently resolving at
a more autonomous baseline (the FRIC-M3 migrator rewrites such configs).

All functions are free of file I/O (ADR-0007 D3): the caller reads
session/project configuration and passes parsed values in. Shipped
preset value-maps live here as data; the planned
``presets/friction/*.yaml`` files (ADR-0016 Q2) will hydrate the same
structures at the infra tier.
"""

from __future__ import annotations

import enum
from collections.abc import Callable
from dataclasses import dataclass, field


class GateEffect(enum.Enum):
    """How a gate resolves for the current session (ADR-0016 D-6, D-9)."""

    ASK = "ask"
    AUTO_ADVANCE = "auto-advance"
    SKIP = "skip"


class UnknownToggleError(ValueError):
    """Raised when a gate name does not map to a known toggle."""


class UnknownPresetError(ValueError):
    """Raised when a preset name is not shipped and not user-supplied."""


AUTO_ADVANCE = "auto-advance"
# Conditional toggle values — auto-advance when the condition holds, else ask.
AUTO_ADVANCE_IF_BOT = "auto-advance-if-bot"
AUTO_ADVANCE_IF_SAFE = "auto-advance-if-safe"
AUTO_ADVANCE_IF_MERGED = "auto-advance-if-merged"
AUTO_ADVANCE_IF_STALE_FREE = "auto-advance-if-stale-free"

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

#: The single shipped base preset (ADR-0022 D-1). Named rather than
#: inlined so the resolver, the config seam, and the docs cannot drift on
#: which posture "the baseline" is.
BASELINE_PRESET = "adaptive"

SHIPPED_PRESETS: dict[str, dict[str, str | int | bool]] = {
    # ADR-0022 D-1: the sole shipped baseline. Its toggle values are
    # unchanged from the ADR-0016 D-10 table's right-hand column, including
    # the author-keyed `auto-advance-if-bot` values for the batch gates
    # (triage_response / thread_resolution / comment_hide, GH-745 F4):
    # bot-authored threads auto-advance, human-authored threads gate —
    # replying to or hiding a teammate's comment is a social act, not a
    # mechanical step. Retiring `strict`/`guided` retires no behaviour
    # `adaptive` had.
    BASELINE_PRESET: {
        "plan_approval": AUTO_ADVANCE,
        "batch_layout": AUTO_ADVANCE,
        "strategy_choice": AUTO_ADVANCE,
        "artifact_preview": AUTO_ADVANCE,
        "triage_response": AUTO_ADVANCE_IF_BOT,
        "thread_resolution": AUTO_ADVANCE_IF_BOT,
        "comment_hide": AUTO_ADVANCE_IF_BOT,
        "yagni_routing": AUTO_ADVANCE,
        "shipping_continuation": AUTO_ADVANCE,
        "request_review": AUTO_ADVANCE,
        "external_notify": "ask",
        "merge": AUTO_ADVANCE,
        "completion_signoff": AUTO_ADVANCE,
        "history_rewrite": AUTO_ADVANCE_IF_SAFE,
        "workspace_choice": AUTO_ADVANCE,
        "branch_cleanup": AUTO_ADVANCE_IF_MERGED,
        "session_adoption": AUTO_ADVANCE_IF_STALE_FREE,
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
        "merge": AUTO_ADVANCE,
    },
    "afk": {
        "session_adoption": AUTO_ADVANCE,
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
    # merge: humans are in the review loop here (ADR-0019). Defaults to
    # True so an unconfigured repo keeps human oversight — the safe pole.
    human_review: bool = True


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

    def visible_record(self) -> str | None:
        """The D-7 one-line transcript record for an auto-advance (ADR-0016).

        Returns ``None`` for ``ask``/``skip`` — only auto-advances need a
        visible record so a present supervisor can notice and override
        mid-flight. Silent auto-advance is a compliance bug (D-7); the
        infra tier both surfaces this string and appends it to the audit
        log + ``doubt_sink``.
        """
        if self.effect is not GateEffect.AUTO_ADVANCE:
            return None
        return f'⚙ gate:{self.gate} auto-advance → "{self.resolved_option}" ({self.reason})'


# Every other floor fires on something about the ACTION — a secret, an
# irreversible write, a cross-author push — so its `ask` is self-explanatory
# and has no config escape by design. `human_review` is the exception: it
# fires on a durable CONFIGURATION fact, and the operator who trips it has
# usually just composed `adaptive + [solo-maintainer, afk]` and been promised
# "full walk-away, merges included". They get an `ask` naming a floor, with
# nothing to say that a project key rather than the preset is holding it
# (GH-1056) — so an unattended run freezes on its first merge with no
# actionable diagnosis. Name the remedy in the reason. The floor does NOT
# move: a session overlay must never lift a durable project fact (ADR-0019),
# because "no human reviews this repo" is a property of the repo, not of how
# this session was launched.
_FLOOR_REMEDIES = {
    "human_review": (
        "humans review this repo — set human_review: false in the matching "
        "projects[] entry of ~/.config/Dev10x/friction.yaml if none do"
    ),
}


def _floors(*, gate: str, context: GateContext) -> list[str]:
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
    # ADR-0019 behaviour 3 (GH-1000). A floor only ever forces `ask`, so
    # expressing the precondition here is what keeps it a precondition
    # and not a grant. Merge-only: the flag's other two consequences are
    # skill concerns, not gate concerns.
    if gate == "merge" and context.human_review:
        floors.append("human_review")
    return floors


def _merge_layers(
    *,
    preset: str,
    overlays: list[str],
    project_overrides: dict[str, str | int | bool],
    session_overrides: dict[str, str | int | bool],
    shipped_presets: dict[str, dict[str, str | int | bool]] | None = None,
    shipped_overlays: dict[str, dict[str, str | int | bool]] | None = None,
    user_presets: dict[str, dict[str, str | int | bool]] | None = None,
) -> dict[str, str | int | bool]:
    # The shipped maps default to the domain constants so pure-domain
    # callers/tests need no I/O; the infra tier injects the YAML-hydrated
    # maps (ADR-0016 D-1) at the MCP boundary. A drift-guard test keeps
    # the two identical.
    base_presets = SHIPPED_PRESETS if shipped_presets is None else shipped_presets
    base_overlays = SHIPPED_OVERLAYS if shipped_overlays is None else shipped_overlays
    presets = {**base_presets, **(user_presets or {})}
    if preset not in presets:
        raise UnknownPresetError(f"Unknown preset {preset!r}; shipped: {sorted(base_presets)}")
    resolved = dict(presets[preset])
    for overlay in overlays:
        if overlay not in base_overlays:
            raise UnknownPresetError(
                f"Unknown overlay {overlay!r}; shipped: {sorted(base_overlays)}"
            )
        resolved.update(base_overlays[overlay])
    resolved.update(project_overrides)
    resolved.update(session_overrides)
    return resolved


@dataclass(frozen=True)
class _Conditional:
    """A conditional toggle value: a predicate plus a reason-fact renderer.

    ``predicate`` decides auto-advance (True) vs ask (False) from the gate
    context; ``fact`` renders the context fact appended to the reason
    string (e.g. ``author=bot``), given the context and whether the
    predicate matched. Adding a new ``AUTO_ADVANCE_IF_*`` value is now a
    table entry, not another copy-pasted branch (audit #845).
    """

    predicate: Callable[[GateContext], bool]
    fact: Callable[[GateContext, bool], str]


def _bool_fact(key: str) -> Callable[[GateContext, bool], str]:
    return lambda _context, matched: f"{key}={'true' if matched else 'false'}"


def _author_fact(context: GateContext, matched: bool) -> str:
    return "author=bot" if matched else f"author={context.author_type or 'human'}"


# Conditional toggle value → (predicate, reason-fact). The predicate's
# truth selects auto-advance; ``fact`` mirrors the exact reason-string
# suffix each branch produced before the table existed.
_CONDITIONAL_TOGGLES: dict[str, _Conditional] = {
    AUTO_ADVANCE_IF_BOT: _Conditional(
        predicate=lambda c: (c.author_type or "human") == "bot",
        fact=_author_fact,
    ),
    AUTO_ADVANCE_IF_SAFE: _Conditional(
        predicate=lambda c: c.provably_safe,
        fact=_bool_fact("safe"),
    ),
    AUTO_ADVANCE_IF_MERGED: _Conditional(
        predicate=lambda c: c.branch_merged,
        fact=_bool_fact("merged"),
    ),
    AUTO_ADVANCE_IF_STALE_FREE: _Conditional(
        predicate=lambda c: not c.session_stale,
        fact=lambda _context, matched: f"stale={'false' if matched else 'true'}",
    ),
}


def _apply_conditions(
    *, gate: str, value: str, context: GateContext, toggles: dict[str, str | int | bool]
) -> tuple[GateEffect, str]:
    """Resolve conditional enum values against the gate context."""
    if value == "skip":
        return GateEffect.SKIP, f"{gate}=skip"
    if value == "ask":
        return GateEffect.ASK, f"{gate}=ask"
    conditional = _CONDITIONAL_TOGGLES.get(value)
    if conditional is not None:
        matched = conditional.predicate(context)
        effect = GateEffect.AUTO_ADVANCE if matched else GateEffect.ASK
        return effect, f"{gate}={value} {conditional.fact(context, matched)}"
    if value == AUTO_ADVANCE:
        return _weight_conditions(gate=gate, context=context, toggles=toggles)
    raise UnknownToggleError(f"Unknown value {value!r} for toggle {gate!r}")


def _weight_conditions(
    *, gate: str, context: GateContext, toggles: dict[str, str | int | bool]
) -> tuple[GateEffect, str]:
    """Weight toggles and the zero-VALID bool condition plain auto-advance."""
    if gate == "batch_layout" and context.overlap_signals is not None:
        floor = int(toggles["batch_ambiguity_floor"])
        if context.overlap_signals < floor:
            return (
                GateEffect.ASK,
                f"{gate}={AUTO_ADVANCE} signals={context.overlap_signals}<floor={floor}",
            )
        return (
            GateEffect.AUTO_ADVANCE,
            f"{gate}={AUTO_ADVANCE} signals={context.overlap_signals}>=floor={floor}",
        )
    if (
        gate in {"triage_response", "thread_resolution", "comment_hide"}
        and context.valid_fixup_count == 0
        and not bool(toggles["zero_valid_autoflow"])
    ):
        return GateEffect.ASK, f"{gate}={AUTO_ADVANCE} zero_valid_autoflow=0"
    return GateEffect.AUTO_ADVANCE, f"{gate}={AUTO_ADVANCE}"


def resolve_gate(
    *,
    gate: str,
    context: GateContext,
    preset: str,
    overlays: list[str] | None = None,
    project_overrides: dict[str, str | int | bool] | None = None,
    session_overrides: dict[str, str | int | bool] | None = None,
    shipped_presets: dict[str, dict[str, str | int | bool]] | None = None,
    shipped_overlays: dict[str, dict[str, str | int | bool]] | None = None,
    user_presets: dict[str, dict[str, str | int | bool]] | None = None,
) -> GateResolution:
    """Resolve one decision gate to ask / auto-advance / skip (ADR-0016).

    Pipeline: merge layers (preset → overlays → project → session
    per-toggle), evaluate conditional values against ``context``, then
    apply safety floors — floors always win (deny-overrides). The
    ``shipped_presets`` / ``shipped_overlays`` maps default to the domain
    constants; the infra tier injects the YAML-hydrated maps (ADR-0016
    D-1).

    Conditional toggle values (``auto-advance-if-*``) resolve through the
    ``_CONDITIONAL_TOGGLES`` table, whose entries are the *function-form*
    of a Policy Rule (ADR-0007): a ``GateContext -> bool`` predicate paired
    with a reason-fact renderer, rather than a persisted ``PolicyRule``
    object. The predicate's truth selects auto-advance vs ask; safety
    floors still override the result.
    """
    if gate not in _ENUM_TOGGLES:
        raise UnknownToggleError(f"Unknown gate {gate!r}; known: {sorted(_ENUM_TOGGLES)}")
    toggles = _merge_layers(
        preset=preset,
        overlays=list(overlays or []),
        project_overrides=dict(project_overrides or {}),
        session_overrides=dict(session_overrides or {}),
        shipped_presets=shipped_presets,
        shipped_overlays=shipped_overlays,
        user_presets=user_presets,
    )
    anchor = bool(toggles["anchor_recommendations"])
    log_to = str(toggles["doubt_sink"])

    floors = _floors(gate=gate, context=context)
    if floors:
        reason = f"floor:{'+'.join(floors)} overrides preset:{preset}"
        remedies = [_FLOOR_REMEDIES[name] for name in floors if name in _FLOOR_REMEDIES]
        return GateResolution(
            gate=gate,
            effect=GateEffect.ASK,
            resolved_option=None,
            log_to=log_to,
            reason=f"{reason} — {'; '.join(remedies)}" if remedies else reason,
            floors_applied=floors,
            anchor_recommendations=anchor,
        )

    value = str(toggles[gate])
    effect, reason = _apply_conditions(gate=gate, value=value, context=context, toggles=toggles)
    return GateResolution(
        gate=gate,
        effect=effect,
        resolved_option="Recommended" if effect is GateEffect.AUTO_ADVANCE else None,
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

    ``review-deferred`` is deprecated (ADR-0019): the durable
    ``human_review`` pref supersedes it, and it is retained for
    read-only back-compat. ``swarm-child`` remains genuinely
    per-dispatch. Neither is a gate concern either way.
    """
    overlays: list[str] = []
    if "solo-maintainer" in active_modes:
        overlays.append("solo-maintainer")
    if walk_away:
        overlays.append("afk")
    return friction_level, overlays


__all__ = [
    "AUTO_ADVANCE",
    "BASELINE_PRESET",
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
