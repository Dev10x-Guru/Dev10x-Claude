"""The global durable-prefs catalog, ``~/.config/Dev10x/friction.yaml`` (GH-812).

One file per machine, keyed by project dir-path globs, cross-repo by
design (ADR-0018). Unlike the per-repo ``config.yaml`` and the
per-worktree ``session.yaml`` (see
:mod:`dev10x.domain.documents.session_yaml`), this document outlives
every checkout it names — which is why it carries garbage-collection
semantics (:func:`reap_dead_projects`) and the repo-identity helpers
that key its ``projects[]`` entries (:func:`repo_stem`,
:func:`match_globs_for_repo`). Split out of ``session_yaml.py`` by
GH-1431.
"""

from __future__ import annotations

import fnmatch
import glob
import os
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.documents.yaml_mapping import load_yaml_mapping
from dev10x.domain.file_locks import atomic_write_text, file_lock
from dev10x.domain.gate_policy import SUPERVISOR_REVIEW_REQUIRED

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
    # above as a deprecated alias (removal: dev10x.domain.deprecations).
    "supervisor_review",
    "protected_branches",
    # Which issue tracker this project uses, so `ensure-base` seeds that
    # tracker's MCP rules and not the other two (GH-768). A workspace fact
    # rather than a pacing preference — same shape as `protected_branches`
    # (GH-1031), and it belongs here for the same reason: the repo-stem
    # `match` globs make one answer cover every worktree of the project.
    "tracker",
    # Which IDE MCP server this project drives, so `ensure-base` seeds its
    # tools and not another IDE's (GH-1261). Same reasoning as `tracker`
    # above, with `none` as the resolved default because most checkouts
    # have no IDE server at all.
    "ide",
    "walk_away",
)

# Public alias for cross-module callers (e.g. the GH-812 R4 migration) that
# need to filter a mapping to the durable set without reaching for the
# underscore-prefixed internal.
DURABLE_KEYS = _DURABLE_KEYS


def _normalize_toplevel(toplevel: str) -> str:
    """Resolve ``toplevel`` to a canonical absolute path for glob matching."""
    try:
        return os.path.realpath(toplevel)
    except OSError:
        return toplevel


def match_globs(toplevel: str, patterns: Any) -> bool:
    """Return ``True`` when ``toplevel`` matches any glob in ``patterns``.

    Each pattern is matched against both the full resolved path (so
    ``/work/dx/**`` works) and the final path segment (so ``*/dev10x-claude``
    or a bare repo name works). ``fnmatch`` semantics — ``*`` spans ``/`` —
    keep the globs forgiving, mirroring ``projects.yaml`` matching.

    This is the canonical PATH-scheme glob matcher (GH-1450) —
    :func:`dev10x.domain.project_match.matches` calls it directly for
    ``MatchScheme.PATH`` rather than maintaining a second, hand-mirrored
    implementation. A config-drift scan exists specifically to catch a
    human unable to see policy drift by reading one file; the drift
    detector cannot itself be a second thing that can drift from the
    runtime gate-resolution path.
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
        return load_yaml_mapping(self.path)

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
            if isinstance(entry, dict) and match_globs(self.toplevel, entry.get("match")):
                return {key: value for key, value in entry.items() if key in _DURABLE_KEYS}
        return None

    @staticmethod
    def render_starter(
        *,
        supervisor_review: str = SUPERVISOR_REVIEW_REQUIRED,
        active_modes: list[str] | None = None,
    ) -> str:
        """Render a fresh global ``friction.yaml`` (schema v2, ADR-0022 D-1/D-2).

        Written once when absent; hand-authored thereafter (add a ``projects:``
        entry per repo). Machines only *read* this file (ADR-0018), so the
        comments survive — no upsert rewrites it.

        v2 carries no ``gate_preset``: there is one shipped baseline, so there
        is nothing to select. ``friction_level`` is likewise absent — the gate
        layer ignores it, and the separate ADR-0002 command-redirect dial of
        the same name lives in the plugin's own config, not here.
        """
        return (
            "# Dev10x global durable session preferences (GH-812, ADR-0018).\n"
            "# One file per machine, keyed by project dir-path globs. Gate policy\n"
            "# (resolve_gate) reads it here; nothing under a repo's .claude/ is\n"
            "# written, so Claude Code's self-settings gate never fires on Dev10x\n"
            "# session state. First matching projects[] entry wins.\n"
            "#\n"
            "# Schema v2 (ADR-0022): auto-advance is the baseline, and the one\n"
            "# question left to answer is whether the supervisor reads the PR\n"
            "# before the next step is allowed. Where that park lands follows\n"
            "# repo shape: before `merge` in a solo repo, before `request_review`\n"
            "# in a team one, where it PRECEDES the team request rather than\n"
            "# replacing it. The `review:cleared` PR label lifts it.\n"
            "defaults:\n"
            f"  supervisor_review: {supervisor_review}  # required | none\n"
            f"  active_modes: {active_modes or []!r}\n"
            "# projects:\n"
            '#   - match: ["*/my-repo", "/abs/path/**"]\n'
            "#     supervisor_review: none  # ADR-0022: no supervisor pass needed\n"
            "#     gate_overlays: [solo-maintainer]\n"
            "#     gate_overrides: {merge: ask}   # per-toggle pins still work\n"
            "#     allowed_overlays: []   # GH-805 overlay guard (empty = no overlays)\n"
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
            return any(match_globs(probe, existing.get("match")) for probe in probes)

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


class PinScope(StrEnum):
    """Scope of a durable pin — a preset, a tracker, an IDE, ... (GH-855, GH-1452).

    ``REPO`` (the default) covers the repo *and every present or future
    worktree of it*, because a pin chosen in one worktree is a statement
    about the repo, not about the ephemeral directory it was chosen
    from. ``REPO_ONLY`` pins the main checkout alone, leaving sibling
    worktrees on ``defaults:``. ``DIR`` pins one directory, verbatim.

    Was previously a bare ``scope: str`` re-declared at eight-plus call
    sites with the same three-line docstring copy-pasted four times
    (GH-1452) — a typo surfaced only inside :func:`match_globs_for_repo`.
    Typing it here means a caller's typo is now a type error, or — at
    the MCP boundary, where FastMCP derives an enum-constrained schema
    from this annotation — a rejected call before any Python runs.
    """

    REPO = "repo"
    REPO_ONLY = "repo-only"
    DIR = "dir"

    @classmethod
    def default(cls) -> PinScope:
        return cls.REPO


#: Back-compat tuple form for callers not yet migrated to :class:`PinScope`.
PIN_SCOPES = tuple(scope.value for scope in PinScope)

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
    scope: PinScope | str = PinScope.default(),
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
            if isinstance(entry, dict) and match_globs(probe, entry.get("match")):
                return {key: value for key, value in entry.items() if key in _DURABLE_KEYS}
    return {}


def seed_safe_baseline_if_absent(*, path: Path | None = None) -> bool:
    """Seed the safe-baseline global ``friction.yaml`` when absent (GH-886).

    The SessionStart detector calls this the first time it sees no global
    ``friction.yaml``. Before ADR-0022 the scaffold was ``friction_level:
    strict``, which made every gate fire until the supervisor chose a posture
    via ``Dev10x:friction-setup`` — replacing the silent guided-preset
    fallback that once auto-merged a PR. With ``strict`` retired (D-1), the
    equivalent safe scaffold is the single baseline plus
    ``supervisor_review: required``: the review boundary holds, the
    preset-independent safety floors are unchanged, and the mechanical steps
    an unconfigured repo has no opinion about stop firing widgets nobody
    asked for.

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
        atomic_write_text(
            target,
            FrictionYamlDocument.render_starter(supervisor_review=SUPERVISOR_REVIEW_REQUIRED),
        )
    return True


#: Deprecated alias (GH-1164), removal in dev10x.domain.deprecations. The scaffold is no
#: longer ``strict``-shaped, so the old name misdescribes what it writes.
seed_strict_baseline_if_absent = seed_safe_baseline_if_absent


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
        doc = load_yaml_mapping(target)
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


@dataclass(frozen=True)
class ReapReport:
    """What a reap pass removed from ``friction.yaml`` (GH-1253)."""

    path: Path
    before: int
    reaped: tuple[str, ...] = ()

    @property
    def after(self) -> int:
        return self.before - len(self.reaped)

    @property
    def changed(self) -> bool:
        return bool(self.reaped)

    def summary(self) -> str:
        if not self.reaped:
            return f"  {self.path}: {self.before} entries, 0 provably dead"
        return (
            f"  {self.path}: {self.before} → {self.after} entries "
            f"(−{len(self.reaped)} whose worktree paths are gone)"
        )


def _absolute_match_paths(entry: dict[str, Any]) -> list[str]:
    match = entry.get("match")
    if not isinstance(match, list):
        return []
    return [pattern for pattern in match if isinstance(pattern, str) and pattern.startswith("/")]


def is_provably_dead(entry: dict[str, Any]) -> bool:
    """Whether every checkout this entry names is gone from disk.

    Deliberately narrow. An entry earns removal only by carrying at
    least one ABSOLUTE path — an ephemeral worktree pin records one
    alongside its glob — and having every such path absent. A
    glob-only entry (``*/tt-pos``) names no checkout that can be
    checked, so it can never be proven dead and is always kept: the
    cost of keeping a dead entry is a wasted glob comparison, while
    the cost of removing a live one is a silently changed posture.
    """
    absolute = _absolute_match_paths(entry)
    if not absolute:
        return False
    return all(not Path(pattern).exists() for pattern in absolute)


def project_entries(*, path: Path | None = None) -> list[dict[str, Any]]:
    """The ``projects[]`` entries as written, for read-only inspection.

    Unlocked on purpose: a dry-run report wants a snapshot, and taking
    the write lock to read one would block a concurrent pin for no gain.
    """
    target = path or Dev10xConfigDir.friction_yaml()
    projects = load_yaml_mapping(target).get("projects")
    if not isinstance(projects, list):
        return []
    return [entry for entry in projects if isinstance(entry, dict)]


def reap_dead_projects(*, path: Path | None = None) -> ReapReport:
    """Drop ``projects[]`` entries whose every named checkout is gone.

    The maintenance machinery is monotone by construction — every other
    command's contract is "ensure X is present" — so nothing has ever
    removed a pin for a worktree that no longer exists. Two thirds of
    this file was such pins when GH-1253 was filed, and first-match-wins
    evaluation walked all of them before reaching a real project, while
    real defects hid among them.

    Shares ``upsert_project_prefs``'s lock and atomic write on the same
    file. Mixing lock helpers here would silently fail to exclude: the
    two sidecar names differ (ADR-0011).
    """
    target = path or Dev10xConfigDir.friction_yaml()
    with file_lock(target):
        doc = load_yaml_mapping(target)
        projects = doc.get("projects")
        if not isinstance(projects, list):
            return ReapReport(path=target, before=0)

        # Count the whole list, not just the entries we can classify. A
        # non-dict entry is kept — nothing this function understands well
        # enough to delete — and the survivors are rebuilt from `projects`,
        # so counting only dicts would make `after` disagree with what the
        # file actually holds.
        dead = [entry for entry in projects if isinstance(entry, dict) and is_provably_dead(entry)]
        if not dead:
            return ReapReport(path=target, before=len(projects))

        reaped = tuple(", ".join(_absolute_match_paths(entry)) for entry in dead)
        doc["projects"] = [entry for entry in projects if entry not in dead]
        atomic_write_text(target, FrictionYamlDocument.render_document(doc))
        return ReapReport(path=target, before=len(projects), reaped=reaped)


__all__ = [
    "DURABLE_KEYS",
    "PIN_SCOPES",
    "FrictionYamlDocument",
    "PinScope",
    "ReapReport",
    "is_provably_dead",
    "match_globs",
    "match_globs_for_repo",
    "project_entries",
    "reap_dead_projects",
    "repo_stem",
    "seed_safe_baseline_if_absent",
    "seed_strict_baseline_if_absent",
    "upsert_project_prefs",
]
