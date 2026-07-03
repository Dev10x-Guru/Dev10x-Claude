"""Gate-policy MCP tool registration (ADR-0016 spike).

Skills call ``resolve_gate`` at each decision gate instead of reading
``friction_level`` / ``active_modes`` / ``walk_away`` themselves — the
tool loads the session policy, applies the preset/overlay/override/floor
pipeline in :mod:`dev10x.domain.gate_policy`, and returns the resolved
effect for the concrete gate instance.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dev10x.domain.common.result import Result, err, ok, to_wire
from dev10x.mcp._app import server

PROJECT_POLICY_RELPATH = Path(".claude") / "Dev10x" / "gate-policy.yaml"


def _project_overrides(toplevel: str) -> dict[str, Any]:
    """Read the project-tier toggle pins (e.g. a team repo's ``merge: ask``).

    A missing or malformed file degrades to no overrides — the preset
    then decides. Shape: ``overrides: {<toggle>: <value>, ...}``.
    """
    import yaml

    path = Path(toplevel) / PROJECT_POLICY_RELPATH
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


async def resolve_gate_for_toplevel(
    *,
    gate: str,
    context: dict[str, Any],
    toplevel: str,
) -> Result[dict[str, Any]]:
    """Resolve one gate against the session + project policy at ``toplevel``."""
    import dataclasses

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

    inputs = SessionYamlDocument(toplevel=toplevel).read_gate_policy_inputs()
    preset, overlays = legacy_session_mapping(
        friction_level=inputs["friction_level"],
        active_modes=inputs["active_modes"],
        walk_away=inputs["walk_away"],
    )
    try:
        resolution = resolve_gate(
            gate=gate,
            context=GateContext(**context),
            preset=preset,
            overlays=overlays,
            project_overrides=_project_overrides(toplevel),
            session_overrides=inputs["gate_overrides"],
        )
    except (UnknownToggleError, UnknownPresetError) as exc:
        return err(str(exc))
    return ok(resolution.to_payload())


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
        Dictionary with keys: gate, effect (ask|auto|skip),
        resolved_option, log_to, reason, floors_applied,
        anchor_recommendations. `{"error": ...}` on unknown gate,
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
