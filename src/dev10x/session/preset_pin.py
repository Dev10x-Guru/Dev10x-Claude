"""Durable preset pinning — the writer seam behind the Phase-0 gate (GH-855).

When the Phase-0 / ``session_adoption`` gate resolves to ``ask``, the
supervisor picks a preset and the choice evaporates at session end: the
domain resolver only ever *reads* ``friction.yaml`` (ADR-0007 D3 keeps it
I/O-free), and ADR-0018 retired the per-repo ``session.yaml`` that could
once have held it. This module is the infra-tier counterpart: it resolves
the repo identity, then persists the pick into the global
``~/.config/Dev10x/friction.yaml`` — outside every repo's ``.claude/``, so
Claude Code's self-settings gate never fires.

**Repo-scoped, not worktree-scoped.** A preset picked while sitting in
``bl-zebra-3`` is a statement about *the repo*: the pin is keyed off the
git common dir (the main working tree), so ``bl-zebra``, ``bl-zebra-1``,
and a ``bl-zebra-9`` created next month all match it. Keying off the
invocation CWD would re-prompt in every sibling worktree, defeating the
point of persisting at all.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from dev10x.domain.common.result import ErrorResult, Result, err, ok
from dev10x.domain.documents.session_yaml import (
    PIN_SCOPES,
    FrictionYamlDocument,
    match_globs_for_repo,
    repo_stem,
    upsert_project_prefs,
)

log = logging.getLogger(__name__)

#: Bound on the git identity lookups. Generous for a local `rev-parse`,
#: short enough that a wedged git degrades to the basename fallback rather
#: than stalling a Phase-0 gate.
_GIT_TIMEOUT_SECONDS = 10.0

#: Values a pinned per-gate override may take. The preset-internal
#: conditional values (``auto-advance-if-*``) are deliberately excluded —
#: they are authored in preset YAML, not chosen at a gate.
PIN_OVERRIDE_VALUES = ("ask", "auto-advance", "skip")

__all__ = [
    "PIN_OVERRIDE_VALUES",
    "RepoIdentity",
    "pin_preset",
    "preset_pin_status",
    "resolve_repo_identity",
    "validate_pin_values",
]


class RepoIdentity(dict[str, Any]):
    """Resolved repo identity: ``name`` (the pin stem), ``root``, ``source``."""


def _common_dir(*, cwd: str | None) -> str | None:
    """Absolute git common dir for ``cwd``, or ``None`` outside a repo.

    ``--git-common-dir`` is the discriminator that makes the pin
    repo-scoped: inside a linked worktree it points at the *main* working
    tree's ``.git``, whereas ``--show-toplevel`` would return the ephemeral
    worktree path.

    Returns ``None`` — not an error — when git is absent, the path is not a
    repo, ``--path-format`` is unsupported (git < 2.31), or the call exceeds
    :data:`_GIT_TIMEOUT_SECONDS`. The caller then falls back to the stemmed
    working-tree basename, which is a degraded but still repo-shaped key;
    failing the pin outright would be worse. The timeout matters because both
    public entry points are served by the long-lived MCP daemon on the
    Phase-0 hot path, where a wedged git must not hang the request.
    """
    import subprocess

    from dev10x.domain.git_context import GitContext

    try:
        return GitContext(cwd=cwd).run(
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        log.debug("git common-dir lookup failed; falling back to basename", exc_info=exc)
        return None


def _bounded_toplevel(*, cwd: str | None) -> str | None:
    """Resolved working tree for ``cwd``, or ``None``, under a timeout.

    Deliberately does NOT use ``GitContext.toplevel``: that is a
    ``cached_property``, so it cannot take a bound, and both callers here sit
    on the Phase-0 path served by the long-lived MCP daemon where a wedged
    git must not hang the request. Same degradation contract as
    :func:`_common_dir` — any failure is ``None``, never a raise.
    """
    import subprocess

    from dev10x.domain.git_context import GitContext

    try:
        toplevel = GitContext(cwd=cwd).run(
            "rev-parse", "--show-toplevel", timeout=_GIT_TIMEOUT_SECONDS
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        log.debug("git toplevel lookup failed", exc_info=exc)
        return None
    return os.path.realpath(toplevel) if toplevel else None


def resolve_repo_identity(*, cwd: str | None = None) -> Result[RepoIdentity]:
    """Resolve the repo stem a pin should be keyed by (GH-855).

    Primary path — the git common dir. ``/work/bl/bl-zebra/.git`` yields
    root ``/work/bl/bl-zebra`` and stem ``bl-zebra`` regardless of which
    worktree the call came from. A bare ``…/bl-zebra.git`` common dir has no
    working tree, so only the name is derived. The common-dir basename is
    used **verbatim**: it is already the main checkout's name, and stemming
    it would widen a repo genuinely named ``advent-2024`` into ``advent``.

    Fallback — the current directory's basename with a trailing ``-<n>``
    stripped (:func:`repo_stem`), for the degenerate case where git cannot
    report a common dir but a toplevel is known.
    """
    common = _common_dir(cwd=cwd)
    if common:
        normalized = os.path.realpath(common.rstrip("/"))
        base = os.path.basename(normalized)
        if base == ".git":
            root = os.path.dirname(normalized)
            return ok(
                RepoIdentity(name=os.path.basename(root), root=root, source="git-common-dir")
            )
        if base.endswith(".git"):
            return ok(RepoIdentity(name=base[: -len(".git")], root=None, source="bare-repo"))
        return ok(RepoIdentity(name=base, root=normalized, source="git-common-dir"))

    fallback_root = _bounded_toplevel(cwd=cwd)
    if not fallback_root:
        return err("Not in a git repository")
    return ok(
        RepoIdentity(
            name=repo_stem(os.path.basename(fallback_root)),
            root=fallback_root,
            source="worktree-basename",
        )
    )


def _probe_path(identity: RepoIdentity) -> str:
    """Absolute path used to test an identity against an entry's globs.

    A bare repo has no working tree, so the name is lifted to ``/<name>``
    rather than left relative. Both the status read and the pin write go
    through this one construction: a relative probe would still *happen* to
    match — ``os.path.realpath`` resolves it against the process CWD and
    ``fnmatch``'s ``*`` is not path-aware — but only accidentally, and a
    later change to either helper would silently break re-pin detection for
    bare repos. Keep both callers on this helper rather than re-deriving.
    """
    return identity["root"] or f"/{identity['name']}"


def preset_pin_status(*, cwd: str | None = None) -> Result[dict[str, Any]]:
    """Report whether this repo already has a ``friction.yaml`` pin (GH-855).

    The read the Phase-0 gate consults *before* offering to remember a
    preset: ``pinned`` is ``False`` only when no ``projects[]`` entry matches,
    which is precisely the "first pick" condition. Asking on every selection
    instead would turn a one-time convenience into recurring friction.
    """
    identity_result = resolve_repo_identity(cwd=cwd)
    if isinstance(identity_result, ErrorResult):
        return err(identity_result.error)
    identity = identity_result.value

    matched = FrictionYamlDocument(toplevel=_probe_path(identity)).matched()
    return ok(
        {
            "pinned": matched is not None,
            "repo_name": identity["name"],
            "repo_root": identity["root"],
            "source": identity["source"],
            "prefs": matched or {},
            "suggested_match": match_globs_for_repo(
                repo_name=identity["name"], repo_root=identity["root"], scope="repo"
            ),
        }
    )


def validate_pin_values(
    *,
    preset: str,
    overlays: list[str] | None,
    gate_overrides: dict[str, str] | None,
) -> str | None:
    """Return an error message for an unwritable pin, or ``None`` when valid.

    Validated against the *same* sources ``resolve_gate`` reads, so this is
    never stricter than the resolver (a user-defined preset in
    ``friction-presets.yaml`` stays pinnable) and never laxer. Without this,
    an agent-driven MCP call with a hallucinated value (``preset="adaptiv"``)
    would be written to the durable ``friction.yaml`` and then make *every*
    subsequent ``resolve_gate`` for that repo fail with ``UnknownPresetError``
    until someone re-pinned by hand. Fail fast at the write instead — the
    same guarantee ``_parse_gate_overrides`` already gives the CLI path.
    """
    from dev10x.config.friction_presets import (
        load_shipped_overlays,
        load_shipped_presets,
        load_user_presets,
    )
    from dev10x.domain.gate_policy import _ENUM_TOGGLES, SHIPPED_OVERLAYS, SHIPPED_PRESETS

    known_presets = set(load_shipped_presets() or SHIPPED_PRESETS) | set(load_user_presets())
    if preset not in known_presets:
        return f"unknown preset {preset!r}; known: {sorted(known_presets)}"

    known_overlays = set(load_shipped_overlays() or SHIPPED_OVERLAYS)
    for overlay in overlays or []:
        if overlay not in known_overlays:
            return f"unknown overlay {overlay!r}; known: {sorted(known_overlays)}"

    for gate, value in (gate_overrides or {}).items():
        if gate not in _ENUM_TOGGLES:
            return f"unknown gate {gate!r}; known: {sorted(_ENUM_TOGGLES)}"
        if value not in PIN_OVERRIDE_VALUES:
            return f"invalid value {value!r} for {gate!r}; expected one of {PIN_OVERRIDE_VALUES}"
    return None


def pin_preset(
    *,
    preset: str,
    overlays: list[str] | None = None,
    gate_overrides: dict[str, str] | None = None,
    scope: str = "repo",
    cwd: str | None = None,
) -> Result[dict[str, Any]]:
    """Persist a Phase-0 preset pick into the global ``friction.yaml`` (GH-855).

    Writes a ``projects[]`` entry keyed by the repo stem (see
    :func:`resolve_repo_identity`), carrying ``gate_preset`` and — when
    supplied — ``gate_overlays`` / ``gate_overrides``. Idempotent: an entry
    already covering this checkout is replaced in place rather than
    duplicated. Nothing is ever written under a repo's ``.claude/``
    (ADR-0018).

    Every value is validated here rather than at the CLI, so the MCP entry
    point gets the same fail-fast guarantee (see :func:`validate_pin_values`).
    """
    if scope not in PIN_SCOPES:
        return err(f"unknown pin scope {scope!r}; expected one of {list(PIN_SCOPES)}")

    invalid = validate_pin_values(preset=preset, overlays=overlays, gate_overrides=gate_overrides)
    if invalid:
        return err(invalid)

    identity_result = resolve_repo_identity(cwd=cwd)
    if isinstance(identity_result, ErrorResult):
        return err(identity_result.error)
    identity = identity_result.value

    if scope == "dir" and not identity["root"]:
        return err("scope 'dir' needs a working tree; this repo resolved as bare")

    match = match_globs_for_repo(
        repo_name=identity["name"], repo_root=identity["root"], scope=scope
    )
    prefs: dict[str, Any] = {"gate_preset": preset}
    if overlays:
        prefs["gate_overlays"] = list(overlays)
    if gate_overrides:
        prefs["gate_overrides"] = dict(gate_overrides)

    # Probe BOTH the repo root and the worktree the pick was made from: the
    # root absorbs an older repo-level entry, the worktree absorbs a legacy
    # worktree-scoped key (``*/bl-zebra-3``). Without the second probe that
    # stale key would survive and, being listed first, keep winning.
    root = _probe_path(identity)
    probes = [root]
    invocation = _bounded_toplevel(cwd=cwd)
    if invocation and invocation not in probes:
        probes.append(invocation)

    written = upsert_project_prefs(toplevel=root, prefs=prefs, match=match, supersedes=probes)
    return ok(
        {
            "path": str(written),
            "match": match,
            "repo_name": identity["name"],
            "repo_root": identity["root"],
            "scope": scope,
            "prefs": prefs,
        }
    )
