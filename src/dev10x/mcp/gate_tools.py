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

from dev10x.domain.common.result import ErrorResult, Result, err, ok, to_wire
from dev10x.domain.file_locks import atomic_append_line
from dev10x.mcp._app import server

# Read/compute half of gate resolution (GH-840). Re-exported here so the
# ``.dev10x/gate-policy.yaml`` constants and ``_project_overrides`` stay
# importable from ``dev10x.mcp.gate_tools`` for existing callers/tests.
from dev10x.mcp.gate_query import (
    LEGACY_PROJECT_POLICY_RELPATH,
    PROJECT_POLICY_RELPATH,
    GateResolutionQuery,
)

if TYPE_CHECKING:  # pragma: no cover
    from dev10x.domain.gate_policy import GateResolution

__all__ = [
    "LEGACY_PROJECT_POLICY_RELPATH",
    "PROJECT_POLICY_RELPATH",
    "GateResolutionQuery",
    "resolve_gate",
    "resolve_gate_for_toplevel",
]

# Session-local sink where auto-advance records accumulate (ADR-0016 #754,
# D-7). Downstream shipping steps fold these into the PR description /
# commit footer per the resolved ``doubt_sink``.
DOUBT_SINK_RELPATH = Path(".claude") / "Dev10x" / "auto-advance-records.md"


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
        atomic_append_line(sink_path, record)
    except OSError:
        pass
    return record


async def resolve_gate_for_toplevel(
    *,
    gate: str,
    context: dict[str, Any],
    toplevel: str,
) -> Result[dict[str, Any]]:
    """Resolve one gate against the session + project policy at ``toplevel``.

    Thin adapter over :class:`~dev10x.mcp.gate_query.GateResolutionQuery`
    (GH-840): the query owns the read + compute; this function routes the
    D-7 side effects (audit log + doubt sink) and builds the wire payload.
    """
    outcome_result = await GateResolutionQuery(gate=gate, context=context, toplevel=toplevel).run()
    if isinstance(outcome_result, ErrorResult):
        return err(outcome_result.error)
    outcome = outcome_result.value

    payload = outcome.resolution.to_payload()
    record = _emit_auto_advance(resolution=outcome.resolution, toplevel=toplevel)
    if record is not None:
        payload["record"] = record
    if outcome.dropped_overlays:
        payload["dropped_overlays"] = outcome.dropped_overlays
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
