"""Persistence boundary for the split session config (GH-774).

Two sibling documents under ``.claude/Dev10x/`` with different lifetimes:

- :class:`ConfigYamlDocument` — ``config.yaml``, **durable** repo
  preferences (``friction_level``, ``active_modes``, and the ADR-0016
  gate keys). Personal, gitignored, and **copied** source→worktree by
  the ``post-checkout`` hook so every worktree of a repo shares them.
- :class:`SessionYamlDocument` — ``session.yaml``, **ephemeral**
  per-worktree state (``branch``, ``tickets``, continuation prompts).
  Seeded fresh per worktree, never carried between them.

Splitting the two escapes Claude Code's ``.claude/`` self-edit gate: the
hook provisions both files, so no runtime ``Write(.claude/…)`` happens on
the hot path (GH-774 comment 3). ``SessionYamlDocument`` stays the single
read facade — its durable readers prefer ``config.yaml`` and fall back to
a pre-split ``session.yaml`` that still carries the durable keys, so the
migration is transparent (ADR-0007 D3 keeps Policy Rules I/O-free).
"""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.file_locks import atomic_write_text, file_lock
from dev10x.domain.friction_level import FrictionLevel

# Durable preference keys (ADR-0018). The global ``friction.yaml`` and the
# legacy per-repo ``config.yaml`` both carry a subset of these; readers
# filter to this set so an unrelated key in a project entry cannot leak
# into the resolver inputs.
_DURABLE_KEYS = (
    "friction_level",
    "active_modes",
    "allowed_overlays",
    "gate_preset",
    "gate_overlays",
    "gate_overrides",
    "walk_away",
)

# Public alias for cross-module callers (e.g. the GH-812 R4 migration) that
# need to filter a mapping to the durable set without reaching for the
# underscore-prefixed internal.
DURABLE_KEYS = _DURABLE_KEYS


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Tolerantly load a YAML mapping, degrading to ``{}`` on any failure.

    A missing, unreadable, or malformed file — including an undecodable
    one (``ValueError`` covers ``UnicodeDecodeError``) — must degrade to
    the soft fallbacks rather than crash the SessionStart hook.
    """
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, ValueError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _coerce_allowed_overlays(value: Any) -> list[str] | None:
    """Coerce a durable ``allowed_overlays`` value to the guard's contract (GH-805).

    ``None`` — key absent, non-list, or malformed — means *no* allow-list is
    declared: the repo has not opted into overlay filtering, so every session
    overlay is honored (back-compat). A ``list`` (including the empty list) is
    an explicit allow-list: any session overlay not named here is dropped
    before gate resolution. The distinction between "unset" and "explicitly
    empty" is load-bearing, so an empty list must survive coercion.
    """
    if not isinstance(value, list):
        return None
    return [str(overlay) for overlay in value]


def _normalize_toplevel(toplevel: str) -> str:
    """Resolve ``toplevel`` to a canonical absolute path for glob matching."""
    try:
        return os.path.realpath(toplevel)
    except OSError:
        return toplevel


def _match_globs(toplevel: str, patterns: Any) -> bool:
    """Return ``True`` when ``toplevel`` matches any glob in ``patterns``.

    Each pattern is matched against both the full resolved path (so
    ``/work/dx/**`` works) and the final path segment (so ``*/dev10x-claude``
    or a bare repo name works). ``fnmatch`` semantics — ``*`` spans ``/`` —
    keep the globs forgiving, mirroring ``projects.yaml`` matching.
    """
    if not isinstance(patterns, list):
        return False
    target = _normalize_toplevel(toplevel)
    base = os.path.basename(target.rstrip("/"))
    for pattern in patterns:
        if not isinstance(pattern, str):
            continue
        if fnmatch.fnmatch(target, pattern) or fnmatch.fnmatch(base, pattern):
            return True
    return False


@dataclass(frozen=True)
class FrictionYamlDocument:
    """Global durable prefs keyed by project dir-path globs (GH-812, ADR-0018).

    Lives at ``~/.config/Dev10x/friction.yaml``, outside every repo's
    ``.claude/`` tree — so writing it never trips Claude Code's self-settings
    gate, and one file serves every worktree/checkout of a repo. Shape mirrors
    ``projects.yaml``::

        defaults:
          friction_level: guided
          active_modes: []
        projects:
          - match: ["*/dev10x-claude", "/work/dx/**"]
            friction_level: adaptive
            gate_preset: adaptive

    ``matched()`` is the first entry whose ``match`` globs hit ``toplevel``;
    ``defaults()`` is the ``defaults:`` base. The durable seam layers them as
    ``{**defaults, **matched}`` and only falls back to the legacy per-repo
    ``config.yaml`` when no entry matches (ADR-0018 D4).
    """

    toplevel: str

    @property
    def path(self) -> Path:
        return Dev10xConfigDir.friction_yaml()

    def _doc(self) -> dict[str, Any]:
        return _load_yaml_mapping(self.path)

    def defaults(self) -> dict[str, Any]:
        """Return the ``defaults:`` durable prefs, filtered to known keys."""
        defaults = self._doc().get("defaults")
        if not isinstance(defaults, dict):
            return {}
        return {key: value for key, value in defaults.items() if key in _DURABLE_KEYS}

    def matched(self) -> dict[str, Any] | None:
        """Return the first matching project entry's durable prefs, or ``None``.

        ``None`` — no ``projects[]`` entry matches ``toplevel`` — signals the
        durable seam to fall back to the legacy per-repo ``config.yaml`` before
        applying ``defaults()`` (ADR-0018 D4 one-cycle migration).
        """
        projects = self._doc().get("projects")
        if not isinstance(projects, list):
            return None
        for entry in projects:
            if isinstance(entry, dict) and _match_globs(self.toplevel, entry.get("match")):
                return {key: value for key, value in entry.items() if key in _DURABLE_KEYS}
        return None

    @staticmethod
    def render_starter(
        *,
        friction_level: str = "guided",
        active_modes: list[str] | None = None,
    ) -> str:
        """Render a fresh global ``friction.yaml`` (defaults + commented example).

        Written once when absent; hand-authored thereafter (add a ``projects:``
        entry per repo). Machines only *read* this file (ADR-0018), so the
        comments survive — no upsert rewrites it.
        """
        return (
            "# Dev10x global durable session preferences (GH-812, ADR-0018).\n"
            "# One file per machine, keyed by project dir-path globs. Gate policy\n"
            "# (resolve_gate) reads it here; nothing under a repo's .claude/ is\n"
            "# written, so Claude Code's self-settings gate never fires on Dev10x\n"
            "# session state. First matching projects[] entry wins.\n"
            "defaults:\n"
            f"  friction_level: {friction_level}  # strict | guided | adaptive\n"
            f"  active_modes: {active_modes or []!r}\n"
            "# projects:\n"
            '#   - match: ["*/my-repo", "/abs/path/**"]\n'
            "#     friction_level: adaptive\n"
            "#     gate_preset: adaptive\n"
            "#     allowed_overlays: []   # GH-805 overlay guard (empty = no overlays)\n"
        )

    # --- Migration seam (GH-812 R4) -------------------------------------
    # Runtime resolvers only *read* friction.yaml; the agent-driven
    # upgrade-cleanup migration is the sanctioned writer. It folds a repo's
    # legacy durable prefs into a projects[] entry via these helpers.

    _MIGRATION_HEADER = (
        "# Dev10x global durable session preferences (GH-812, ADR-0018).\n"
        "# One file per machine, keyed by project dir-path globs. Gate policy\n"
        "# (resolve_gate) reads it here at runtime; only the agent-driven\n"
        "# upgrade-cleanup migration (GH-812 R4) writes it. First matching\n"
        "# projects[] entry wins.\n"
    )

    @staticmethod
    def match_globs_for(toplevel: str) -> list[str]:
        """Return the ``match`` globs for a repo: basename glob + exact path.

        Mirrors the ``projects.yaml`` example shape (a forgiving ``*/repo``
        basename glob plus the canonical absolute path so the entry resolves
        from any worktree/checkout of the repo).
        """
        target = _normalize_toplevel(toplevel)
        base = os.path.basename(target.rstrip("/"))
        globs = [target]
        if base:
            globs.insert(0, f"*/{base}")
        return globs

    @staticmethod
    def with_project(
        doc: dict[str, Any],
        *,
        match: list[str],
        prefs: dict[str, Any],
    ) -> dict[str, Any]:
        """Upsert a ``projects[]`` entry into ``doc``, returning a new mapping.

        The entry is keyed by its ``match`` list: an existing entry with the
        identical ``match`` is replaced (idempotent re-runs), otherwise the
        entry is appended. Only known durable keys survive from ``prefs`` so
        an unrelated key cannot leak into the resolver inputs.
        """
        base = dict(doc) if isinstance(doc, dict) else {}
        raw_projects = base.get("projects")
        projects = list(raw_projects) if isinstance(raw_projects, list) else []
        entry: dict[str, Any] = {"match": list(match)}
        entry.update({key: value for key, value in prefs.items() if key in _DURABLE_KEYS})
        replaced = False
        merged: list[Any] = []
        for existing in projects:
            if isinstance(existing, dict) and existing.get("match") == list(match):
                merged.append(entry)
                replaced = True
            else:
                merged.append(existing)
        if not replaced:
            merged.append(entry)
        base["projects"] = merged
        return base

    @staticmethod
    def render_document(doc: dict[str, Any]) -> str:
        """Render a full ``friction.yaml`` document (header + YAML body).

        Used by the migration writer. A PyYAML round-trip does not preserve
        the hand-authored example comments, so the canonical header is
        re-prepended to keep the file self-documenting.
        """
        body = yaml.safe_dump(doc or {}, sort_keys=False, default_flow_style=False)
        return FrictionYamlDocument._MIGRATION_HEADER + body


def seed_strict_baseline_if_absent(*, path: Path | None = None) -> bool:
    """Seed a ``strict`` baseline global ``friction.yaml`` when absent (GH-886).

    The SessionStart detector calls this the first time it sees no global
    ``friction.yaml``: a ``strict`` scaffold makes every gate fire until the
    supervisor explicitly chooses a posture via ``Dev10x:friction-setup``,
    replacing the silent guided-preset fallback (the failure mode that once
    auto-merged a PR).

    Race-safe and idempotent: an exclusive lock guards a re-check so two
    worktrees hitting SessionStart concurrently cannot both write, and the
    atomic write leaves no truncated file on a crash (GH-827 / ADR-0011). A
    present file is left untouched. Returns ``True`` only when this call wrote.
    """
    target = path or Dev10xConfigDir.friction_yaml()
    if target.exists():
        return False
    with file_lock(target):
        if target.exists():
            return False
        atomic_write_text(target, FrictionYamlDocument.render_starter(friction_level="strict"))
    return True


#: Synthetic active-mode name under which ``Dev10x:friction-setup`` records
#: per-step skips it chose. The resolver honors step ``skip`` actions from any
#: active mode's ``mode_extensions`` (references/execution-modes.md resolution
#: 3b/3d), so a project-scoped step skip needs no new plumbing.
FRICTION_SETUP_SKIP_MODE = "friction-setup-skips"


def upsert_project_prefs(
    *, toplevel: str, prefs: dict[str, Any], path: Path | None = None
) -> Path:
    """Upsert this repo's durable gate prefs into the global ``friction.yaml`` (GH-886).

    The gate axis of ``Dev10x:friction-setup``: writes a ``projects[]`` entry
    (keyed by this repo's dir-path globs) carrying ``gate_preset`` /
    ``gate_overlays`` / ``gate_overrides``. Only durable keys survive (via
    :meth:`FrictionYamlDocument.with_project`). Concurrency-safe and idempotent
    — an exclusive lock guards the read-modify-write and the atomic write leaves
    no truncated file (GH-827 / ADR-0011); re-running with the same match list
    replaces the entry rather than appending. Returns the file written.
    """
    target = path or Dev10xConfigDir.friction_yaml()
    match = FrictionYamlDocument.match_globs_for(toplevel)
    with file_lock(target):
        doc = _load_yaml_mapping(target)
        updated = FrictionYamlDocument.with_project(doc, match=match, prefs=prefs)
        atomic_write_text(target, FrictionYamlDocument.render_document(updated))
    return target


def set_playbook_modes(
    *,
    skill: str,
    active_modes: list[str],
    skip_steps: list[str] | None = None,
    home: Path | None = None,
) -> Path:
    """Write the playbook axis of ``Dev10x:friction-setup`` to a global playbook (GH-886).

    Persists ``active_modes`` (the modes the supervisor enabled) into
    ``~/.config/Dev10x/playbooks/<skill>.yaml`` — the tier-2 project playbook the
    work-on resolver reads (instructions.md Phase 3 step 6). ``skip_steps`` names
    play-step subjects to always drop (e.g. ``"Draft Job Story"``); they are
    recorded as ``mode_extensions`` step ``skip`` actions under the synthetic
    :data:`FRICTION_SETUP_SKIP_MODE`, which is appended to ``active_modes`` so the
    resolver applies them (no new plumbing — execution-modes resolution 3b/3d).

    Concurrency-safe (exclusive lock + atomic write, GH-827 / ADR-0011) and
    idempotent — ``active_modes`` is replaced wholesale on each run. Returns the
    file written.

    ``skill`` is interpolated into the playbook filename, so it is validated
    against ``[A-Za-z0-9_-]+`` first: without this a value like
    ``../../../../tmp/evil`` would traverse outside the playbooks directory and
    write an arbitrary file (a manipulated CLI invocation / prompt injection).
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]+", skill):
        raise ValueError(
            f"invalid skill name {skill!r}: expected [A-Za-z0-9_-]+ (no path separators)"
        )
    base = home or Dev10xConfigDir.home()
    target = base / "playbooks" / f"{skill}.yaml"
    modes = list(active_modes)
    with file_lock(target):
        doc = _load_yaml_mapping(target)
        if skip_steps:
            extensions = doc.get("mode_extensions")
            extensions = dict(extensions) if isinstance(extensions, dict) else {}
            extensions[FRICTION_SETUP_SKIP_MODE] = {
                "steps": {subject: {"skip": True} for subject in skip_steps}
            }
            doc["mode_extensions"] = extensions
            if FRICTION_SETUP_SKIP_MODE not in modes:
                modes.append(FRICTION_SETUP_SKIP_MODE)
        doc["active_modes"] = modes
        atomic_write_text(target, yaml.safe_dump(doc, sort_keys=False, default_flow_style=False))
    return target


def legacy_durable_prefs(*, toplevel: str) -> dict[str, Any]:
    """Durable keys from the legacy per-repo files ONLY (GH-812 R4).

    Reads ``config.yaml`` (durable home) with a pre-split ``session.yaml``
    fallback, filtered to :data:`_DURABLE_KEYS`. Deliberately excludes the
    global ``friction.yaml`` — the migration seam folds *these* legacy prefs
    into it, so consulting friction.yaml here would be circular.
    """
    session = _load_yaml_mapping(SessionYamlDocument(toplevel=toplevel).path)
    config = ConfigYamlDocument(toplevel=toplevel).data()
    merged = {**session, **config}
    return {key: value for key, value in merged.items() if key in _DURABLE_KEYS}


@dataclass(frozen=True)
class ConfigYamlDocument:
    """Legacy per-repo durable prefs at ``.claude/Dev10x/config.yaml`` (GH-774).

    Retired by ADR-0018 in favor of the global :class:`FrictionYamlDocument`;
    still read as a one-cycle migration fallback for repos not yet present in
    ``friction.yaml``. ``upgrade-cleanup`` / ``plugin-doctor`` fold it in.
    """

    toplevel: str

    @property
    def path(self) -> Path:
        return Path(self.toplevel) / ".claude" / "Dev10x" / "config.yaml"

    def data(self) -> dict[str, Any]:
        return _load_yaml_mapping(self.path)

    @staticmethod
    def render(
        *,
        friction_level: str = "guided",
        active_modes: list[str] | None = None,
        allowed_overlays: list[str] | None = None,
    ) -> str:
        """Render the canonical ``config.yaml`` body (durable prefs).

        ``allowed_overlays`` is emitted only when explicitly provided so the
        canonical body is byte-identical to the pre-GH-805 shape when the repo
        has not opted into the overlay guard — an omitted key reads back as
        ``None`` (permissive) via :func:`_coerce_allowed_overlays`.
        """
        body = (
            "# Dev10x durable repo preferences (GH-774) — friction level and\n"
            "# active modes. Gitignored + copied to each worktree by the\n"
            "# post-checkout hook. Ephemeral per-worktree state (branch,\n"
            "# tickets) lives in the sibling session.yaml.\n"
            f"friction_level: {friction_level}  # strict | guided | adaptive\n"
            f"active_modes: {active_modes or []!r}\n"
        )
        if allowed_overlays is not None:
            body += (
                "# GH-805: local repo-character overlay allow-list. Any session\n"
                "# overlay not named here (e.g. solo-maintainer) is dropped before\n"
                "# gate resolution and flagged at SessionStart. An empty list\n"
                "# honors no high-autonomy overlay — correct for a team repo.\n"
                "# Omit the key entirely to allow every overlay (back-compat).\n"
                f"allowed_overlays: {list(allowed_overlays)!r}\n"
            )
        return body


@dataclass(frozen=True)
class SessionYamlDocument:
    """Read facade for the session config; writer for ephemeral ``session.yaml``."""

    toplevel: str

    @property
    def path(self) -> Path:
        return Path(self.toplevel) / ".claude" / "Dev10x" / "session.yaml"

    def _load(self) -> dict[str, Any]:
        """Load the ephemeral ``session.yaml`` mapping."""
        return _load_yaml_mapping(self.path)

    def _durable(self) -> dict[str, Any]:
        """Durable prefs (ADR-0018 precedence).

        1. A matching ``friction.yaml`` project entry (``{**defaults, **entry}``)
           wins — the global, gate-free source of truth.
        2. Else the legacy per-repo ``config.yaml`` (with a pre-split
           ``session.yaml`` fallback) is honored so un-migrated repos are
           untouched.
        3. Else ``friction.yaml`` ``defaults`` apply to a brand-new repo.
        """
        friction = FrictionYamlDocument(toplevel=self.toplevel)
        matched = friction.matched()
        if matched is not None:
            return {**friction.defaults(), **matched}
        legacy = {**self._load(), **ConfigYamlDocument(toplevel=self.toplevel).data()}
        if legacy:
            return legacy
        return friction.defaults()

    def durable_prefs(self) -> dict[str, Any]:
        """Explicit durable prefs (config wins, pre-split session fallback).

        Unlike the typed readers this applies **no** defaulting, so ``None``
        distinguishes "unset" from "explicitly guided" — the migration seam
        ``dev10x session seed`` uses to lift a pre-split ``session.yaml``'s
        durable keys into ``config.yaml`` without overwriting them.
        """
        return self._durable()

    def read_friction_level(self) -> FrictionLevel:
        """Return the session friction level, defaulting on any read failure."""
        return FrictionLevel.from_yaml(self._durable().get("friction_level"))

    def read_active_modes(self) -> list[str]:
        """Return the active-modes list, or an empty list when unset/invalid."""
        modes = self._durable().get("active_modes")
        return modes if isinstance(modes, list) else []

    def read_friction_and_modes(self) -> tuple[FrictionLevel, list[str]]:
        """Return ``(friction_level, active_modes)`` from the durable prefs."""
        data = self._durable()
        level = FrictionLevel.from_yaml(data.get("friction_level"))
        modes = data.get("active_modes")
        return level, (modes if isinstance(modes, list) else [])

    def read_allowed_overlays(self) -> list[str] | None:
        """Return the durable overlay allow-list, or ``None`` when unset (GH-805).

        ``None`` means the repo has not opted into overlay filtering — every
        session overlay is honored (back-compat). A list (including ``[]``) is
        an explicit allow-list: a session overlay not named here is dropped
        before gate resolution. This is a **local** repo-character preference:
        it lives in the gitignored, worktree-copied ``config.yaml`` (never a
        committed artifact), so a stale ``active_modes: [solo-maintainer]`` a
        team repo copied worktree-wide is neutralised without a shared pin.
        """
        return _coerce_allowed_overlays(self._durable().get("allowed_overlays"))

    def read_gate_policy_inputs(self) -> dict[str, Any]:
        """Return the resolver inputs for ``gate_policy`` (ADR-0016).

        All of these are **durable** — read from ``config.yaml`` with the
        pre-split ``session.yaml`` fallback. Two input styles coexist
        (ADR-0016 D-4): new-style ``gate_preset`` / ``gate_overlays`` name a
        preset + overlays directly; when absent, the legacy keys
        (``friction_level``, ``active_modes``, ``walk_away``) feed
        :func:`dev10x.domain.gate_policy.legacy_session_mapping`. Either way
        ``gate_overrides`` carries per-toggle session overrides.

        ``allowed_overlays`` (GH-805) is the repo-character overlay allow-list:
        ``None`` when unset (permissive), else the whitelist the resolver
        filters the computed overlays against before resolving a gate.
        """
        data = self._durable()
        modes = data.get("active_modes")
        overrides = data.get("gate_overrides")
        preset = data.get("gate_preset")
        overlays = data.get("gate_overlays")
        return {
            "friction_level": FrictionLevel.from_yaml(data.get("friction_level")).value,
            "active_modes": modes if isinstance(modes, list) else [],
            "walk_away": bool(data.get("walk_away", False)),
            "gate_overrides": overrides if isinstance(overrides, dict) else {},
            "gate_preset": preset if isinstance(preset, str) else None,
            "gate_overlays": overlays if isinstance(overlays, list) else [],
            "allowed_overlays": _coerce_allowed_overlays(data.get("allowed_overlays")),
        }

    # ADR-0018: session identity (branch/tickets) is no longer persisted
    # under .claude/Dev10x/session.yaml. Staleness reads it from plan-sync
    # via dev10x.domain.session_document.read_plan_identity instead, and
    # nothing writes session.yaml — so the self-settings gate never fires.
    # ``_load``/``path`` survive only to read a legacy pre-split session.yaml
    # as a durable-prefs migration fallback in ``_durable``.


__all__ = [
    "DURABLE_KEYS",
    "FRICTION_SETUP_SKIP_MODE",
    "ConfigYamlDocument",
    "FrictionYamlDocument",
    "SessionYamlDocument",
    "legacy_durable_prefs",
    "seed_strict_baseline_if_absent",
    "set_playbook_modes",
    "upsert_project_prefs",
]
