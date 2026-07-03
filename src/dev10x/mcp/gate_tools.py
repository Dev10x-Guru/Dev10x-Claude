"""Gate-policy MCP tool registration (ADR-0016).

Skills call ``resolve_gate`` at each decision gate instead of reading
``friction_level`` / ``active_modes`` / ``walk_away`` themselves — the
tool loads the session policy, hydrates the shipped presets from
``presets/friction/*.yaml`` (ADR-0016 D-1), applies the
preset/overlay/override/floor pipeline in
:mod:`dev10x.domain.gate_policy`, and returns the resolved effect for the
concrete gate instance. Auto-advances surface a visible D-7 record that is
also appended to the audit log and the configured ``doubt_sink`` (#754).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from dev10x.domain.common.result import Result, err, ok, to_wire
from dev10x.mcp._app import server

if TYPE_CHECKING:  # pragma: no cover
    from dev10x.domain.documents.session_yaml import SessionYamlDocument
    from dev10x.domain.gate_policy import GateResolution

# Durable, git-tracked project pin (ADR-0016 #752). The spike wrote the
# pin under ``.claude/Dev10x/`` which this repo gitignores wholesale, so a
# team repo's ``merge: ask`` could not be committed or shared — defeating
# the D-8 "repo character is a durable property" intent (review finding on
# #746). The pin now lives at a git-tracked path; the legacy location is
# still read as a fallback for un-migrated repos.
PROJECT_POLICY_RELPATH = Path(".dev10x") / "gate-policy.yaml"
LEGACY_PROJECT_POLICY_RELPATH = Path(".claude") / "Dev10x" / "gate-policy.yaml"

# Session-local sink where auto-advance records accumulate (ADR-0016 #754,
# D-7). Downstream shipping steps fold these into the PR description /
# commit footer per the resolved ``doubt_sink``.
DOUBT_SINK_RELPATH = Path(".claude") / "Dev10x" / "auto-advance-records.md"


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


def _computed_session_stale(*, toplevel: str, session_doc: SessionYamlDocument) -> bool:
    """Compute ``session_stale`` for the session_adoption gate (GH-742 F1).

    This is a **branch-only fallback**: ``current_tickets`` is empty because
    the boundary has no invocation ticket context, so a branch match is the
    only way freshness can be proven here (the predicate's ticket-overlap
    signal is unreachable on this path). A caller that knows the current
    invocation's tickets should pass ``session_stale`` in the gate context
    explicitly rather than rely on this computed fallback (Round 1 review C2).
    """
    from dev10x.domain.session_staleness import session_stale

    identity = session_doc.read_session_identity()
    return session_stale(
        recorded_branch=identity["branch"],
        current_branch=_current_branch(toplevel),
        recorded_tickets=identity["tickets"],
        current_tickets=[],
    )


def _emit_auto_advance(*, resolution: GateResolution, toplevel: str) -> str | None:
    """Surface + persist a D-7 auto-advance record (ADR-0016 #754).

    Returns the visible record string (for the tool payload) and, as a
    side effect, appends it to the audit log and the doubt_sink file.
    Returns ``None`` for ``ask``/``skip`` — only auto-advances get a
    record. Silent auto-advance is a compliance bug (D-7).
    """
    record = resolution.visible_record()
    if record is None:
        return None
    from dev10x.hooks.audit_emit import append_gate_record

    append_gate_record(
        gate=resolution.gate,
        option=resolution.resolved_option,
        reason=resolution.reason,
        sink=resolution.log_to,
    )
    sink_path = Path(toplevel) / DOUBT_SINK_RELPATH
    try:
        sink_path.parent.mkdir(parents=True, exist_ok=True)
        with sink_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{record}\n")
    except OSError:
        pass
    return record


async def resolve_gate_for_toplevel(
    *,
    gate: str,
    context: dict[str, Any],
    toplevel: str,
) -> Result[dict[str, Any]]:
    """Resolve one gate against the session + project policy at ``toplevel``."""
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
    unknown = sorted(set(context) - known_fields)
    if unknown:
        return err(f"Unknown context fields: {unknown}; known: {sorted(known_fields)}")

    session_doc = SessionYamlDocument(toplevel=toplevel)
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

    # session_adoption keys on computed staleness (GH-742 F1 seam) unless
    # the caller supplied session_stale explicitly.
    resolved_context = dict(context)
    if gate == "session_adoption" and "session_stale" not in resolved_context:
        resolved_context["session_stale"] = _computed_session_stale(
            toplevel=toplevel, session_doc=session_doc
        )

    # An empty load (presets/friction/ absent at runtime) falls back to the
    # domain default constants via ``None`` — the drift-guard test keeps the
    # two identical, so degradation is safe and resolve_gate never breaks for
    # want of the YAML files.
    try:
        resolution = resolve_gate(
            gate=gate,
            context=GateContext(**resolved_context),
            preset=preset,
            overlays=overlays,
            project_overrides=_project_overrides(toplevel),
            session_overrides=inputs["gate_overrides"],
            shipped_presets=load_shipped_presets() or None,
            shipped_overlays=load_shipped_overlays() or None,
            user_presets=load_user_presets(),
        )
    except (UnknownToggleError, UnknownPresetError) as exc:
        return err(str(exc))

    payload = resolution.to_payload()
    record = _emit_auto_advance(resolution=resolution, toplevel=toplevel)
    if record is not None:
        payload["record"] = record
    return ok(payload)


@server.tool()
async def resolve_gate(
    gate: str,
    context: dict | None = None,
    cwd: str | None = None,
) -> dict:
    """Resolve a decision gate to ask/auto/skip per the session's gate policy.

    Args:
        gate: Gate-class toggle name (e.g. "thread_resolution", "merge").
        context: Facts about this gate instance (author_type, destructive,
            overlap_signals, valid_fixup_count, ...). Omitted facts
            resolve in the safe direction.
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: gate, effect (ask|auto-advance|skip),
        resolved_option, log_to, reason, floors_applied,
        anchor_recommendations, and — on an auto-advance — a `record`
        with the visible D-7 line. `{"error": ...}` on unknown gate,
        context field, or preset.
    """
    from dev10x.domain.git_context import GitContext
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        toplevel = GitContext().toplevel
        if toplevel is None:
            return to_wire(err("Not in a git repository"))
        return to_wire(
            await resolve_gate_for_toplevel(
                gate=gate, context=dict(context or {}), toplevel=toplevel
            )
        )
