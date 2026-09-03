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
import glob
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.file_locks import atomic_write_text, file_lock
from dev10x.domain.friction_level import FrictionLevel
from dev10x.domain.gate_policy import (
    SUPERVISOR_REVIEW_NONE,
    SUPERVISOR_REVIEW_REQUIRED,
    coerce_supervisor_review,
)

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
    "human_review",
    # ADR-0022 D-2: does the supervisor read this PR before the next step is
    # allowed? `required` | `none`. Supersedes `human_review`, which is kept
    # above as a deprecated alias for one release.
    "supervisor_review",
    "protected_branches",
    # Which issue tracker this project uses, so `ensure-base` seeds that
    # tracker's MCP rules and not the other two (GH-768). A workspace fact
    # rather than a pacing preference — same shape as `protected_branches`
    # (GH-1031), and it belongs here for the same reason: the repo-stem
    # `match` globs make one answer cover every worktree of the project.
    "tracker",
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


def _coerce_human_review(value: Any) -> bool:
    """Coerce a durable ``human_review`` value to the review posture (ADR-0019).

    ``True`` — the default — means humans (including the session
    supervisor) are in the review loop: reviewers get requested and the
    unresolved-threads / review-requested DoD checks run. Only a real
    boolean ``False`` disables them.

    An absent, ``None``, or non-boolean value (e.g. the string ``"no"``)
    resolves to ``True`` so a malformed setting fails toward MORE
    oversight, never less — the same safe direction ``allowed_overlays``
    takes when it cannot parse a policy.
    """
    return value if isinstance(value, bool) else True


def _coerce_protected_branches(value: Any) -> list[str] | None:
    """Coerce a durable ``protected_branches`` value to the push guard's contract.

    ``None`` — key absent, non-list, or holding nothing usable — means the
    project declares no override, so ``git-push-safe.sh`` applies its own
    default set (``main master develop development staging trunk``). A list
    REPLACES that default, which is why an entry that coerces to empty must
    read as unset rather than as "protect nothing": a typo'd pref must never
    silently strip force-push protection from ``main``.

    Entries are stringified and blank-stripped so a stray ``null`` or empty
    string in the YAML list cannot become a ``--protected ''`` flag that
    matches no branch. ``None`` is dropped before stringifying — ``str(None)``
    is the truthy ``"None"``, which would otherwise be pushed as a real
    branch name.
    """
    if not isinstance(value, list):
        return None
    branches = [
        str(branch).strip() for branch in value if branch is not None and str(branch).strip()
    ]
    return branches or None


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
            "#     human_review: false    # ADR-0019: no humans in the review loop\n"
        )

    # --- Migration seam (GH-812 R4) -------------------------------------
    # Runtime resolvers only *read* friction.yaml. The agent-driven
    # upgrade-cleanup migration writes it via these helpers, folding a repo's
    # legacy durable prefs into a projects[] entry — but it is not the only
    # sanctioned writer: `dev10x session set-friction` / `session pin` write
    # per-project entries too (GH-1003).

    _MIGRATION_HEADER = (
        "# Dev10x global durable session preferences (GH-812, ADR-0018).\n"
        "# One file per machine, keyed by project dir-path globs. Gate policy\n"
        "# (resolve_gate) reads it here at runtime. Sanctioned writers: the\n"
        "# agent-driven upgrade-cleanup migration (GH-812 R4), `dev10x session\n"
        "# set-friction`, and `dev10x session pin`. First matching projects[]\n"
        "# entry wins.\n"
    )

    @staticmethod
    def match_globs_for(toplevel: str) -> list[str]:
        """Return the ``match`` globs for a repo: basename glob + exact path.

        Mirrors the ``projects.yaml`` example shape (a forgiving ``*/repo``
        basename glob plus the canonical absolute path so the entry resolves
        from any worktree/checkout of the repo).

        .. deprecated:: GH-855
           ``toplevel`` inside a worktree is the *worktree* path, so this
           emits a worktree-scoped key (``*/bl-zebra-3``) that re-prompts in
           every sibling worktree. Prefer
           :func:`match_globs_for_repo`, which keys off the repo stem.
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
        supersedes: list[str] | None = None,
    ) -> dict[str, Any]:
        """Upsert a ``projects[]`` entry into ``doc``, returning a new mapping.

        An existing entry with the identical ``match`` list is replaced
        (idempotent re-runs). ``supersedes`` widens that to *repo* identity
        (GH-855): every path listed there is probed against each existing
        entry's globs, and a hit replaces that entry in place. Callers pass
        both the repo root and the worktree the pick was made from, so a
        re-pin from a sibling worktree AND a legacy worktree-scoped key like
        ``*/bl-zebra-3`` are both folded into the repo-stem entry. Any
        *further* entries that also match are dropped: leaving them behind
        would keep a shadowed duplicate for the same repo, which is exactly
        the never-duplicate invariant this upsert owes its callers.

        Only known durable keys survive from ``prefs`` so an unrelated key
        cannot leak into the resolver inputs.
        """
        base = dict(doc) if isinstance(doc, dict) else {}
        raw_projects = base.get("projects")
        projects = list(raw_projects) if isinstance(raw_projects, list) else []
        entry: dict[str, Any] = {"match": list(match)}
        entry.update({key: value for key, value in prefs.items() if key in _DURABLE_KEYS})
        probes = list(supersedes or [])

        def _supersedes(existing: Any) -> bool:
            if not isinstance(existing, dict):
                return False
            if existing.get("match") == list(match):
                return True
            return any(_match_globs(probe, existing.get("match")) for probe in probes)

        replaced = False
        merged: list[Any] = []
        for existing in projects:
            if not _supersedes(existing):
                merged.append(existing)
            elif not replaced:
                merged.append(entry)
                replaced = True
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


#: Scope of a durable preset pin (GH-855). ``repo`` — the default — covers
#: the repo *and every present or future worktree of it*, because a preset
#: chosen in one worktree is a statement about the repo, not about the
#: ephemeral directory it was chosen from.
PIN_SCOPES = ("repo", "repo-only", "dir")

_WORKTREE_SUFFIX = re.compile(r"-\d+$")


def repo_stem(name: str) -> str:
    """Strip a trailing ``-<n>`` worktree suffix from a directory name (GH-855).

    Only used on the **fallback** derivation path, where the sole signal
    available is the current directory's basename (``bl-zebra-3`` →
    ``bl-zebra``). The primary path reads the git common dir, whose basename
    is already the main working tree's name and is used verbatim — stripping
    there would over-widen a repo legitimately named ``advent-2024`` into
    ``advent``.

    Returns ``name`` unchanged when stripping would leave nothing.
    """
    stripped = _WORKTREE_SUFFIX.sub("", name)
    return stripped or name


def match_globs_for_repo(
    *,
    repo_name: str,
    repo_root: str | None = None,
    scope: str = "repo",
) -> list[str]:
    """Return the ``friction.yaml`` ``match`` globs for a repo pin (GH-855).

    * ``repo`` (default) — ``["*/<name>", "*/<name>-*"]``: the main checkout
      plus every worktree of it, including ones created next month. This is
      what makes a preset picked inside ``<name>-3`` stick for ``<name>-9``.
    * ``repo-only`` — ``["*/<name>"]``: the main checkout alone; sibling
      worktrees named ``<name>-<n>`` keep falling back to ``defaults:``.
      Since GH-978 a *linked* worktree that matches no entry of its own
      resolves its durable prefs at the repo root, so this scope no longer
      excludes such worktrees — it only withholds the ``-*`` sibling glob.
      Use ``dir`` scope to pin a single directory verbatim.
    * ``dir`` — ``[<resolved repo_root>]``: this one directory, verbatim.

    ``repo_root`` is required for ``dir`` scope and ignored otherwise.

    ``repo_name`` comes from a directory basename, so any ``fnmatch``
    metacharacter in it (``*``, ``?``, ``[…]``) is escaped before
    interpolation. A checkout literally named ``foo*`` would otherwise
    persist a pattern matching *unrelated* repos on the machine, silently
    widening their gate posture — a durable change with no signal to those
    repos' owners. Escaping (rather than rejecting, as the sibling
    ``set_playbook_modes`` does for a path segment) keeps an oddly-named
    checkout pinnable while making the stored glob literal.
    """
    if scope not in PIN_SCOPES:
        raise ValueError(f"unknown pin scope {scope!r}; expected one of {list(PIN_SCOPES)}")
    if scope == "dir":
        if not repo_root:
            raise ValueError("scope 'dir' requires repo_root")
        return [_normalize_toplevel(repo_root)]
    if not repo_name:
        raise ValueError("repo_name is required for repo-scoped globs")
    stem = glob.escape(repo_name)
    if scope == "repo-only":
        return [f"*/{stem}"]
    return [f"*/{stem}", f"*/{stem}-*"]


# Durable keys the gate-axis writers (`dev10x session set-friction`,
# `dev10x session pin`) own outright. Omitting an axis on those commands means
# "back to the preset", so these are replaced wholesale and never carried
# forward from the entry being superseded. Every OTHER durable key belongs to
# a different axis (review posture, push protection, overlay guard) that the
# gate commands never take as input — see :func:`_carried_durable_prefs`.
_GATE_AXIS_KEYS = ("gate_preset", "gate_overlays", "gate_overrides")


def _carried_durable_prefs(*, doc: dict[str, Any], probes: list[str]) -> dict[str, Any]:
    """Durable prefs the first entry matching any of ``probes`` already holds.

    Resolution is FIRST-MATCH-WINS (GH-1068 F3), so writing a narrower entry —
    e.g. a worktree-path-scoped ``*/agent-<id>`` from ``set-friction`` — makes
    that entry the only one the resolver ever sees for the worktree. Written as
    a bare preset it silently DROPS whatever the repo's own entry carried, and
    ``human_review`` is the key that hurts: ``_coerce_human_review`` fails
    toward ``True``, so a repo deliberately configured ``human_review: false``
    starts demanding human review inside the worktree with no signal that a
    setting was lost.

    ``probes`` is ordered most-specific-first, so an entry already covering the
    exact checkout wins over the repo-root entry it would otherwise inherit.
    """
    projects = doc.get("projects")
    if not isinstance(projects, list):
        return {}
    for probe in probes:
        for entry in projects:
            if isinstance(entry, dict) and _match_globs(probe, entry.get("match")):
                return {key: value for key, value in entry.items() if key in _DURABLE_KEYS}
    return {}


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
    *,
    toplevel: str,
    prefs: dict[str, Any],
    path: Path | None = None,
    match: list[str] | None = None,
    supersedes: list[str] | None = None,
    inherit_from: list[str] | None = None,
) -> Path:
    """Upsert this repo's durable gate prefs into the global ``friction.yaml`` (GH-886).

    The gate axis of ``Dev10x:friction-setup``: writes a ``projects[]`` entry
    carrying ``gate_preset`` / ``gate_overlays`` / ``gate_overrides``. Only
    durable keys survive (via :meth:`FrictionYamlDocument.with_project`).
    Concurrency-safe and idempotent — an exclusive lock guards the
    read-modify-write and the atomic write leaves no truncated file (GH-827 /
    ADR-0011). Returns the file written.

    ``match`` supplies the entry key; callers pinning a *repo* pass the
    repo-stem globs from :func:`match_globs_for_repo` (GH-855). It defaults to
    the legacy path-derived globs, which are worktree-scoped when ``toplevel``
    is a worktree. ``supersedes`` lists the paths whose existing entries this
    write absorbs (defaulting to ``toplevel``), so a repo already covered by an
    older entry is updated in place instead of gaining a shadowed duplicate.

    ``inherit_from`` (most-specific path first, defaulting to ``supersedes``)
    names the checkouts whose currently-effective entry this write inherits
    non-gate durable keys from, so a narrower entry cannot silently drop the
    ``human_review`` / ``protected_branches`` / overlay-guard settings the
    entry it shadows carried (GH-1068 F3). A worktree caller passes the repo
    root here as well, since no existing entry matches the worktree path.
    """
    target = path or Dev10xConfigDir.friction_yaml()
    entry_match = match if match is not None else FrictionYamlDocument.match_globs_for(toplevel)
    probes = supersedes if supersedes is not None else [toplevel]
    inherit_probes = list(inherit_from) if inherit_from is not None else list(probes)
    with file_lock(target):
        doc = _load_yaml_mapping(target)
        carried = {
            key: value
            for key, value in _carried_durable_prefs(doc=doc, probes=inherit_probes).items()
            if key not in _GATE_AXIS_KEYS and key not in prefs
        }
        updated = FrictionYamlDocument.with_project(
            doc, match=entry_match, prefs={**carried, **prefs}, supersedes=probes
        )
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


# Overlays that also name an execution mode, so mode-filtering consumers see
# the same posture the gate resolver does (GH-1003). `legacy_session_mapping`
# maps modes -> overlays; this is the missing reverse leg. `afk` is absent by
# design: it is overlay-only (its legacy source is the `walk_away` bool, not a
# mode), it is not documented in references/active-modes.md, and no consumer
# filters playbook steps or DoD checks on it. Structural modes
# (`review-deferred`, `swarm-child`) have no overlay and stay active_modes-only.
_OVERLAY_DERIVED_MODES: dict[str, str] = {"solo-maintainer": "solo-maintainer"}


def _modes_with_overlays_folded_in(data: dict[str, Any]) -> list[str]:
    """Return ``active_modes`` unioned with the modes its overlays imply.

    A repo that migrated to ``gate_preset`` + ``gate_overlays`` names its
    posture only in overlay vocabulary. Without this fold, ``resolve_gate``
    saw solo-maintainer while ``Dev10x:verify-acc-dod``'s mode filter and
    ``Dev10x:work-on``'s playbook ``modes:`` mapping saw nothing — one
    posture, two answers, so the "Review requested" DoD check fired red on
    a PR whose ``request_review`` gate had already resolved to ``skip``.

    Declared modes keep their order and position; derived ones append.
    """
    modes = data.get("active_modes")
    resolved = list(modes) if isinstance(modes, list) else []
    overlays = data.get("gate_overlays")
    if not isinstance(overlays, list):
        return resolved
    for overlay in overlays:
        mode = _OVERLAY_DERIVED_MODES.get(overlay)
        if mode is not None and mode not in resolved:
            resolved.append(mode)
    return resolved


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
        """Return the active modes, including any derived from overlays.

        See :func:`_modes_with_overlays_folded_in` — an entry that names a
        posture only in ``gate_overlays`` still reports the equivalent mode.
        """
        return _modes_with_overlays_folded_in(self._durable())

    def read_friction_and_modes(self) -> tuple[FrictionLevel, list[str]]:
        """Return ``(friction_level, active_modes)`` from the durable prefs."""
        data = self._durable()
        level = FrictionLevel.from_yaml(data.get("friction_level"))
        return level, _modes_with_overlays_folded_in(data)

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

    def read_human_review(self) -> bool:
        """Deprecated alias for :meth:`read_supervisor_review` (ADR-0022 D-2).

        ``human_review``'s name conflates two different readers — the session
        supervisor and the wider team — which is why it could only ever gate
        ``merge``: it had no way to express "the supervisor reads it first,
        *then* we ask the team". ``supervisor_review`` splits them.

        Retained for one release so un-migrated callers keep working.
        ``required`` maps to ``True``, ``none`` to ``False``, preserving the
        boolean's polarity and its unset → ``True`` safe direction.
        """
        return self.read_supervisor_review() == SUPERVISOR_REVIEW_REQUIRED

    def read_supervisor_review(self, *, data: dict[str, Any] | None = None) -> str:
        """Return whether the supervisor reads this PR first (ADR-0022 D-2).

        One durable, project-wide fact answering exactly one question: *must
        the supervisor read this PR before the next step is allowed?*
        ``required`` inserts a park; ``none`` removes it. Where the park sits
        follows repo shape (ADR-0022 D-3) — before ``merge`` in a solo repo,
        before ``request_review`` in a team one — which the gate resolver
        decides, not this reader.

        ``required`` is a floor and therefore a PRECONDITION for autonomy,
        never a grant: the ``merge: ask`` project pin (ADR-0016 D-8), the
        ``allowed_overlays`` guard (ADR-0017), and
        ``merge_config.solo_maintainer`` all remain independent vetoes.

        Absent, unrecognised, or malformed values read as ``required``, so an
        unconfigured repo keeps oversight and every typo fails toward more of
        it. The deprecated ``human_review`` boolean is honoured as an alias
        for one release: ``true`` → ``required``, ``false`` → ``none``. An
        explicit ``supervisor_review`` always wins over it.

        ``data`` lets a caller that has already loaded ``_durable()`` reuse
        it — the reader is not memoised, and the gate path resolves this on
        every call.
        """
        prefs = self._durable() if data is None else data
        if "supervisor_review" in prefs:
            return coerce_supervisor_review(prefs["supervisor_review"])
        if "human_review" in prefs:
            return (
                SUPERVISOR_REVIEW_REQUIRED
                if _coerce_human_review(prefs["human_review"])
                else SUPERVISOR_REVIEW_NONE
            )
        return SUPERVISOR_REVIEW_REQUIRED

    def read_protected_branches(self) -> list[str] | None:
        """Return the durable force-push protected-branch override (GH-1031).

        ``None`` means the project declares no override and
        ``git-push-safe.sh`` applies its own default set
        (``main master develop development staging trunk``). A list replaces
        that default wholesale, so a project protecting ``release/*`` must
        re-list the integration branches it still wants covered.

        This exists so a project with a non-standard integration branch does
        not have to pass ``protected_branches`` on every ``push_safe`` call —
        an unattended agent never would, which is precisely when an
        unprotected force-push does the most damage.
        """
        return _coerce_protected_branches(self._durable().get("protected_branches"))

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

        ``supervisor_review`` (ADR-0022 D-2, superseding ADR-0019's
        ``human_review``) rides along because the review-boundary gate needs
        it and ``_durable()`` is not memoised — reading it via
        :meth:`read_supervisor_review` instead would re-open and re-parse the
        same YAML a second time on every gate resolution.
        """
        data = self._durable()
        modes = data.get("active_modes")
        overrides = data.get("gate_overrides")
        preset = data.get("gate_preset")
        overlays = data.get("gate_overlays")
        raw_level = data.get("friction_level")
        return {
            # ``None`` when the key is absent — the gate layer needs to tell
            # "no legacy posture declared" (resolve at the ADR-0022 D-1
            # baseline) from "explicitly strict" (a retired preset name that
            # must fail loudly rather than resolve at a MORE autonomous
            # baseline). Defaulting to ``FrictionLevel.default()`` here, as
            # this reader used to, collapsed those two cases into "strict".
            "friction_level": (
                FrictionLevel.from_yaml(raw_level).value
                if isinstance(raw_level, str) and raw_level.strip()
                else None
            ),
            "active_modes": modes if isinstance(modes, list) else [],
            "walk_away": bool(data.get("walk_away", False)),
            "gate_overrides": overrides if isinstance(overrides, dict) else {},
            "gate_preset": preset if isinstance(preset, str) else None,
            "gate_overlays": overlays if isinstance(overlays, list) else [],
            "allowed_overlays": _coerce_allowed_overlays(data.get("allowed_overlays")),
            # ADR-0022 D-2/D-5. Rides along rather than being re-read via
            # :meth:`read_supervisor_review`: ``_durable()`` is not memoised,
            # so a second typed read would re-open and re-parse the same YAML
            # on every gate resolution.
            "supervisor_review": self.read_supervisor_review(data=data),
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
    "PIN_SCOPES",
    "ConfigYamlDocument",
    "FrictionYamlDocument",
    "SessionYamlDocument",
    "legacy_durable_prefs",
    "match_globs_for_repo",
    "repo_stem",
    "seed_strict_baseline_if_absent",
    "set_playbook_modes",
    "upsert_project_prefs",
]
