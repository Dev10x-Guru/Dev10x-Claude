"""Service-layer gate resolution query (GH-840).

``resolve_gate_for_toplevel`` had grown into a ~100-line MCP handler that
read the session + project policy, computed the preset/overlay/override/floor
pipeline, resolved the gate, AND performed the D-7 side effects inline —
untestable off the MCP surface and mixing read/compute/write in one place.

This module owns the **read + compute** half as a
:class:`GateResolutionQuery` that returns an assembled
:class:`GateResolutionOutcome` (the concrete ``GateContext``, the
``GateResolution``, and any overlays dropped by the durable-mode guard).
The MCP adapter in :mod:`dev10x.mcp.gate_tools` stays thin: it runs the
query, routes the side effects (audit log + doubt sink), and builds the
wire payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dev10x.domain.common.result import Result, err, ok

if TYPE_CHECKING:  # pragma: no cover
    from dev10x.domain.gate_policy import GateContext, GateResolution

# Durable, git-tracked project pin (ADR-0016 #752). The spike wrote the
# pin under ``.claude/Dev10x/`` which this repo gitignores wholesale, so a
# team repo's ``merge: ask`` could not be committed or shared — defeating
# the D-8 "repo character is a durable property" intent (review finding on
# #746). The pin now lives at a git-tracked path; the legacy location is
# still read as a fallback for un-migrated repos.
PROJECT_POLICY_RELPATH = Path(".dev10x") / "gate-policy.yaml"
LEGACY_PROJECT_POLICY_RELPATH = Path(".claude") / "Dev10x" / "gate-policy.yaml"


def _read_overrides(path: Path) -> dict[str, Any]:
    """Read an ``overrides:`` mapping from a gate-policy file, or ``{}``."""
    import yaml

    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, ValueError, yaml.YAMLError):
        return {}
    if not isinstance(data, dict):
        return {}
    overrides = data.get("overrides")
    return overrides if isinstance(overrides, dict) else {}


def _project_overrides(toplevel: str) -> dict[str, Any]:
    """Read the project-tier toggle pins, preferring the durable path.

    A missing or malformed file degrades to no overrides — the preset then
    decides. Shape: ``overrides: {<toggle>: <value>, ...}``.
    """
    root = Path(toplevel)
    primary = _read_overrides(root / PROJECT_POLICY_RELPATH)
    if primary:
        return primary
    return _read_overrides(root / LEGACY_PROJECT_POLICY_RELPATH)


def _current_branch(toplevel: str) -> str | None:
    """Current git branch at ``toplevel``, or ``None`` when undeterminable."""
    from dev10x.domain.git_context import GitContext

    branch = GitContext(cwd=toplevel).branch
    return None if branch == "unknown" else branch


def _computed_session_stale(*, toplevel: str) -> bool:
    """Compute ``session_stale`` for the session_adoption gate (GH-742 F1).

    Identity comes from the plan-sync state (ADR-0018): the retired
    ``.claude/Dev10x/session.yaml`` no longer stores ``branch``/``tickets`` —
    plan-sync already persists both (MCP-written, gate-free).

    This is a **branch-only fallback**: ``current_tickets`` is empty because
    the boundary has no invocation ticket context, so a branch match is the
    only way freshness can be proven here (the predicate's ticket-overlap
    signal is unreachable on this path). A caller that knows the current
    invocation's tickets should pass ``session_stale`` in the gate context
    explicitly rather than rely on this computed fallback (Round 1 review C2).
    """
    from dev10x.domain.session_document import read_plan_identity
    from dev10x.domain.session_staleness import session_stale

    identity = read_plan_identity(toplevel=toplevel)
    return session_stale(
        recorded_branch=identity["branch"],
        current_branch=_current_branch(toplevel),
        recorded_tickets=identity["tickets"],
        current_tickets=[],
    )


@dataclass(frozen=True)
class GateResolutionOutcome:
    """Read/compute result of a gate query, ready for side-effect routing.

    ``context`` is the concrete ``GateContext`` that was resolved (including
    any computed ``session_stale`` fallback); ``dropped_overlays`` lists the
    overlays the durable-mode guard removed before resolution.
    """

    context: GateContext
    resolution: GateResolution
    dropped_overlays: list[str]


@dataclass(frozen=True)
class GateResolutionQuery:
    """Assemble the gate policy inputs and resolve one gate — no side effects.

    Reading the session/project policy and computing the preset/overlay
    pipeline is separated here from the MCP adapter's write/format concerns
    (GH-840), so the read+compute half is testable off the MCP surface.
    """

    gate: str
    context: dict[str, Any]
    toplevel: str

    async def run(self) -> Result[GateResolutionOutcome]:
        import dataclasses

        from dev10x.config.friction_presets import (
            load_shipped_overlays,
            load_shipped_presets,
            load_user_presets,
        )
        from dev10x.domain.documents.session_yaml import SessionYamlDocument
        from dev10x.domain.gate_policy import (
            GateContext,
            UnknownPresetError,
            UnknownToggleError,
            legacy_session_mapping,
            resolve_gate,
        )

        known_fields = {field.name for field in dataclasses.fields(GateContext)}
        unknown = sorted(set(self.context) - known_fields)
        if unknown:
            return err(f"Unknown context fields: {unknown}; known: {sorted(known_fields)}")

        session_doc = SessionYamlDocument(toplevel=self.toplevel)
        inputs = session_doc.read_gate_policy_inputs()

        # New-style session keys (gate_preset/gate_overlays) win; otherwise map
        # the legacy friction_level/active_modes/walk_away shape (ADR-0016 D-4).
        if inputs["gate_preset"] is not None:
            preset = inputs["gate_preset"]
            # A transition-period file may set gate_preset while still carrying
            # legacy active_modes. When gate_overlays is omitted, inherit the
            # legacy active_modes/walk_away-derived overlays so a solo-maintainer
            # or afk overlay is not silently dropped (Round 1 review C3). An
            # explicit gate_overlays list wins wholesale.
            if inputs["gate_overlays"]:
                overlays = inputs["gate_overlays"]
            else:
                _, overlays = legacy_session_mapping(
                    friction_level=inputs["friction_level"],
                    active_modes=inputs["active_modes"],
                    walk_away=inputs["walk_away"],
                )
        else:
            preset, overlays = legacy_session_mapping(
                friction_level=inputs["friction_level"],
                active_modes=inputs["active_modes"],
                walk_away=inputs["walk_away"],
            )

        # GH-805 durable-mode guard: a repo may declare a local, gitignored
        # ``allowed_overlays`` allow-list in config.yaml. Any overlay not on it —
        # e.g. a stale ``solo-maintainer`` copied worktree-wide by post-checkout —
        # is dropped BEFORE resolution so its request_review/external_notify/merge
        # skips are never honored. Dropping only ever removes autonomy, so it can
        # never make a gate less safe. ``None`` means no allow-list (permissive).
        dropped_overlays: list[str] = []
        allowed_overlays = inputs["allowed_overlays"]
        if allowed_overlays is not None:
            dropped_overlays = [o for o in overlays if o not in allowed_overlays]
            overlays = [o for o in overlays if o in allowed_overlays]

        # session_adoption keys on computed staleness (GH-742 F1 seam) unless
        # the caller supplied session_stale explicitly.
        resolved_context = dict(self.context)
        if self.gate == "session_adoption" and "session_stale" not in resolved_context:
            resolved_context["session_stale"] = _computed_session_stale(toplevel=self.toplevel)

        gate_context = GateContext(**resolved_context)

        # An empty load (presets/friction/ absent at runtime) falls back to the
        # domain default constants via ``None`` — the drift-guard test keeps the
        # two identical, so degradation is safe and resolve_gate never breaks for
        # want of the YAML files.
        try:
            resolution = resolve_gate(
                gate=self.gate,
                context=gate_context,
                preset=preset,
                overlays=overlays,
                project_overrides=_project_overrides(self.toplevel),
                session_overrides=inputs["gate_overrides"],
                shipped_presets=load_shipped_presets() or None,
                shipped_overlays=load_shipped_overlays() or None,
                user_presets=load_user_presets(),
            )
        except (UnknownToggleError, UnknownPresetError) as exc:
            return err(str(exc))

        return ok(
            GateResolutionOutcome(
                context=gate_context,
                resolution=resolution,
                dropped_overlays=dropped_overlays,
            )
        )
