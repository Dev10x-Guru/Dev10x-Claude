"""Read facade over the session config's three documents (GH-774, GH-1431).

Durable prefs live in three documents with different lifetimes, each in
its own module:

- :class:`~dev10x.domain.documents.friction_yaml.FrictionYamlDocument` —
  the **global** ``~/.config/Dev10x/friction.yaml``, cross-repo, keyed by
  project globs, with its own reap/GC semantics (ADR-0018).
- :class:`~dev10x.domain.documents.config_yaml.ConfigYamlDocument` — the
  legacy **per-repo** ``.claude/Dev10x/config.yaml``, a one-cycle
  migration fallback.
- :class:`SessionYamlDocument` (here) — the **per-worktree**
  ``.claude/Dev10x/session.yaml``, now read only as a pre-split fallback.

``SessionYamlDocument`` stays the single read facade: ``_durable`` layers
the three in ADR-0018 precedence and the typed readers coerce the result
(ADR-0007 D3 keeps Policy Rules I/O-free).

The names that moved out in GH-1431 are re-exported below so every
existing ``from dev10x.domain.documents.session_yaml import ...`` keeps
resolving; new code should import from the owning module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dev10x.domain.documents.config_yaml import (
    FRICTION_SETUP_SKIP_MODE,
    ConfigYamlDocument,
    set_playbook_modes,
)
from dev10x.domain.documents.friction_yaml import (
    _DURABLE_KEYS,
    DURABLE_KEYS,
    PIN_SCOPES,
    FrictionYamlDocument,
    PinScope,
    ReapReport,
    is_provably_dead,
    match_globs,
    match_globs_for_repo,
    project_entries,
    reap_dead_projects,
    repo_stem,
    seed_safe_baseline_if_absent,
    seed_strict_baseline_if_absent,
    upsert_project_prefs,
)
from dev10x.domain.documents.yaml_mapping import load_yaml_mapping
from dev10x.domain.friction_level import FrictionLevel
from dev10x.domain.gate_policy import (
    SUPERVISOR_REVIEW_NONE,
    SUPERVISOR_REVIEW_REQUIRED,
    coerce_supervisor_review,
)


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


# Overlays that also name an execution mode, so mode-filtering consumers see
# the same posture the gate resolver does (GH-1003). Since GH-1162 this is the
# ONLY direction that survives: overlays -> modes. The reverse leg was the
# retired read-compat seam, and a config that still needs it is refused rather
# than translated. `afk` is absent by design: it is overlay-only, it is not
# documented in references/active-modes.md, and no consumer filters playbook
# steps or DoD checks on it. Structural modes (`review-deferred`,
# `swarm-child`) have no overlay and stay active_modes-only.
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
    fallback, filtered to :data:`DURABLE_KEYS`. Deliberately excludes the
    global ``friction.yaml`` — the migration seam folds *these* legacy prefs
    into it, so consulting friction.yaml here would be circular.
    """
    session = load_yaml_mapping(SessionYamlDocument(toplevel=toplevel).path)
    config = ConfigYamlDocument(toplevel=toplevel).data()
    merged = {**session, **config}
    return {key: value for key, value in merged.items() if key in _DURABLE_KEYS}


@dataclass(frozen=True)
class SessionYamlDocument:
    """Read facade for the session config; writer for ephemeral ``session.yaml``."""

    toplevel: str

    @property
    def path(self) -> Path:
        return Path(self.toplevel) / ".claude" / "Dev10x" / "session.yaml"

    def _load(self) -> dict[str, Any]:
        """Load the ephemeral ``session.yaml`` mapping."""
        return load_yaml_mapping(self.path)

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

        Retained until its removal version in
        :mod:`dev10x.domain.deprecations`.
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
        until its removal version in :mod:`dev10x.domain.deprecations`:
        ``true`` → ``required``, ``false`` → ``none``. An
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
        pre-split ``session.yaml`` fallback. ``gate_preset`` /
        ``gate_overlays`` name the preset and overlays directly, and
        ``gate_overrides`` carries per-toggle session overrides.

        The v1 keys (``friction_level``, ``walk_away``, and
        ``active_modes``) still ride along, but nothing translates them
        into a posture any more (GH-1162). They are reported so
        :func:`dev10x.domain.gate_policy.legacy_policy_keys` can *detect*
        an un-migrated config and refuse it by name — resolving one at the
        sole remaining baseline would widen autonomy on a repo that had
        pinned a stricter posture.

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
    "PinScope",
    "ReapReport",
    "SessionYamlDocument",
    "is_provably_dead",
    "legacy_durable_prefs",
    "match_globs",
    "match_globs_for_repo",
    "project_entries",
    "reap_dead_projects",
    "repo_stem",
    "seed_safe_baseline_if_absent",
    "seed_strict_baseline_if_absent",
    "set_playbook_modes",
    "upsert_project_prefs",
]
