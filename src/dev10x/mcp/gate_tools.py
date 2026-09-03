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
    "human_review_status",
    "pin_gate_preset",
    "pin_tracker",
    "preset_pin_status",
    "resolve_gate",
    "resolve_gate_for_toplevel",
    "supervisor_review_status",
    "tracker_status",
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
    if outcome.ignored_context_fields:
        payload["ignored_context_fields"] = outcome.ignored_context_fields
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


@server.tool()
async def preset_pin_status(cwd: str | None = None) -> dict:
    """Report whether this repo already has a durable friction.yaml preset pin.

    Consult this BEFORE offering to remember a Phase-0 preset choice:
    `pinned: false` is the "first pick" condition that warrants the
    "Remember this preset?" gate. Re-asking on every selection turns a
    one-time convenience into recurring friction.

    Args:
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: pinned (bool), repo_name (the repo stem the
        pin is keyed by — derived from the git common dir, so it is the
        same from every worktree), repo_root, source, prefs (the matched
        entry's durable keys, or {}), suggested_match (the globs a `repo`
        scoped pin would write). `{"error": ...}` outside a git repo.
    """
    from dev10x.session import preset_pin
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return to_wire(preset_pin.preset_pin_status(cwd=cwd))


def _read_supervisor_review() -> Result[dict[str, Any]]:
    """Shared body for `supervisor_review_status` and its deprecated alias.

    Callers bind the effective CWD (GH-979) before invoking this.
    """
    from dev10x.domain.documents.session_yaml import SessionYamlDocument
    from dev10x.domain.gate_policy import SUPERVISOR_REVIEW_REQUIRED
    from dev10x.domain.git_context import GitContext
    from dev10x.mcp.gate_query import _policy_toplevel

    toplevel = GitContext().toplevel
    if toplevel is None:
        return err("Not in a git repository")
    # Resolve through the same GH-978 repo-root fallback the gate uses
    # (GH-1000). One durable fact must not have two answers: in a linked
    # worktree matching no friction.yaml glob, a raw toplevel here would
    # report `required` — sending the skills off to park — while
    # resolve_gate read the repo's `none` and lifted its floor.
    document = SessionYamlDocument(toplevel=_policy_toplevel(toplevel))
    supervisor_review = document.read_supervisor_review()
    return ok(
        {
            "supervisor_review": supervisor_review,
            # Deprecated alias, emitted for one release so callers that
            # still branch on the boolean keep working (ADR-0022 D-2).
            "human_review": supervisor_review == SUPERVISOR_REVIEW_REQUIRED,
            "repo_root": toplevel,
        }
    )


@server.tool()
async def supervisor_review_status(cwd: str | None = None) -> dict:
    """Report whether the supervisor reads this project's PRs (ADR-0022 D-2).

    The sanctioned way for a skill to read the durable `supervisor_review`
    posture. Skills MUST call this rather than reading
    `~/.config/Dev10x/friction.yaml` directly or re-deriving the
    first-match-wins glob precedence in prose — the same rule
    `resolve_gate` enforces for the rest of the gate policy.

    Where the park lands follows repo shape (ADR-0022 D-3): before `merge`
    in a solo repo, before `request_review` in a team one. `required` never
    REMOVES a step — in a team repo it precedes the team review request
    rather than replacing it. `none` is a *precondition* for autonomy,
    never a grant, since the `merge: ask` project pin and
    `allowed_overlays` remain independent vetoes.

    Args:
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: supervisor_review ("required" | "none" —
        "required" when unset or malformed, so a bad value fails toward
        MORE oversight), human_review (the deprecated boolean alias),
        repo_root. `{"error": ...}` outside a git repo.
    """
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return to_wire(_read_supervisor_review())


@server.tool()
async def human_review_status(cwd: str | None = None) -> dict:
    """Deprecated alias for `supervisor_review_status` (ADR-0022 D-2).

    `human_review` conflated the session supervisor with the wider team,
    which is why it could only ever gate `merge`. Retained for one release;
    returns the same payload, including the boolean `human_review` key.

    Args:
        cwd: Effective working directory (GH-979).

    Returns:
        Same as `supervisor_review_status`.
    """
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return to_wire(_read_supervisor_review())


@server.tool()
async def pin_gate_preset(
    preset: str,
    overlays: list[str] | None = None,
    gate_overrides: dict | None = None,
    scope: str = "repo",
    cwd: str | None = None,
) -> dict:
    """Persist a Phase-0 preset choice to the global friction.yaml (GH-855).

    Keys the `projects[]` entry off the **repo stem** resolved from the git
    common dir, not the invocation CWD — so a preset chosen inside worktree
    `<repo>-3` also covers `<repo>`, `<repo>-1`, and any `<repo>-9` created
    later. Idempotent: an entry already covering this checkout is replaced
    in place, never duplicated. Nothing is written under the repo's
    `.claude/` (ADR-0018), so the self-settings gate never fires.

    Args:
        preset: Gate preset to pin (strict | guided | adaptive).
        overlays: Overlay names layered on the preset (e.g. ["solo-maintainer"]).
        gate_overrides: Per-toggle deviations, e.g. {"merge": "ask"}.
        scope: "repo" (default — repo + all present/future worktrees),
            "repo-only" (main checkout only), or "dir" (this directory).
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: path, match, repo_name, repo_root, scope,
        prefs. `{"error": ...}` on an unknown scope or outside a git repo.
    """
    from dev10x.session import preset_pin
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return to_wire(
            preset_pin.pin_preset(
                preset=preset,
                overlays=list(overlays) if overlays else None,
                gate_overrides=dict(gate_overrides) if gate_overrides else None,
                scope=scope,
                cwd=cwd,
            )
        )


@server.tool()
async def tracker_status(cwd: str | None = None) -> dict:
    """Report this repo's issue tracker, and whether it was chosen (GH-768).

    Consult this BEFORE asking the onboarding tracker-choice question:
    `pinned: false` is the "never answered" condition that warrants the
    gate. Re-asking a settled workspace fact on every bootstrap is the
    friction the gate exists to remove.

    Args:
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: pinned (bool — a `projects[]` entry names a
        tracker), tracker (the resolved value, defaulting to "linear"),
        source ("project" | "defaults" | "default"), repo_name, repo_root,
        choices. `{"error": ...}` outside a git repository.
    """
    from dev10x.session import tracker_pin
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return to_wire(tracker_pin.tracker_status(cwd=cwd))


@server.tool()
async def pin_tracker(
    tracker: str,
    scope: str = "repo",
    cwd: str | None = None,
) -> dict:
    """Persist the project's issue tracker to the global friction.yaml (GH-768).

    `ensure-base` / `seed_worktree` then seed only that tracker's MCP
    rules — a Jira user stops collecting ~35 inert Linear allows while
    their own Atlassian tools prompt on first use.

    Keyed off the **repo stem** from the git common dir like
    `pin_gate_preset`, so a choice made inside worktree `<repo>-3` also
    covers `<repo>` and any `<repo>-9` created later. Idempotent: an
    entry already covering this checkout is replaced, never duplicated.

    Args:
        tracker: One of "linear", "jira", "github". An unrecognised value
            is an error, not a silent fallback to the default.
        scope: "repo" (default — repo + all present/future worktrees),
            "repo-only" (main checkout only), or "dir" (this directory).
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: path, match, repo_name, repo_root, scope,
        prefs. `{"error": ...}` on an unknown tracker or scope, or
        outside a git repository.
    """
    from dev10x.session import tracker_pin
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return to_wire(tracker_pin.pin_tracker(tracker=tracker, scope=scope, cwd=cwd))
