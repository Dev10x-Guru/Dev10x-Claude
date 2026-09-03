"""One-shot v1 → v2 durable-config migration (GH-1166, ADR-0022).

Every durable config written before ADR-0022 names its posture in v1
vocabulary — ``gate_preset`` / ``friction_level`` selecting one of three
shipped postures, ``human_review`` as a boolean, ``walk_away`` as a
separate flag. Those shapes resolve today only because
``legacy_session_mapping`` and the ``GateResolutionQuery.run`` fallback
translate them. GH-1162 retires that seam; this module converts the
stores first, so the retirement cannot silently change a repo's posture.

The **safety direction is one-way**: no config may resolve to MORE
autonomy after migration than before. ``supervisor_review`` is written
``required`` unless the source config carried an explicit, unambiguous
low-oversight statement (``supervisor_review: none``, or a real boolean
``human_review: false`` under a preset that was not itself asking for
more oversight). Absent, unrecognised, and malformed inputs all resolve
to ``required``, matching :func:`coerce_supervisor_review` and the
ADR-0022 risk table.

Two stores are walked:

* the global ``~/.config/Dev10x/friction.yaml`` — its ``defaults:``
  block and every ``projects[]`` entry, migrated in place;
* the legacy per-repo ``.claude/Dev10x/config.yaml``, which is *folded
  into* ``friction.yaml`` as a ``projects[]`` entry rather than
  rewritten. ADR-0018 keeps Dev10x out of a repo's ``.claude/`` tree, so
  the legacy file is read and left alone; migrating it means making the
  global store carry its posture, which is what survives the fallback
  read being retired.

``.dev10x/gate-policy.yaml`` is deliberately NOT walked: its
``overrides:`` are per-toggle pins, still valid verbatim under v2.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from dev10x.domain.common.result import Result, ok
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.documents.session_yaml import (
    DURABLE_KEYS,
    ConfigYamlDocument,
    FrictionYamlDocument,
    match_globs_for_repo,
    repo_stem,
)
from dev10x.domain.file_locks import atomic_write_text, file_lock
from dev10x.domain.gate_policy import (
    BASELINE_PRESET,
    SOLO_OVERLAY,
    SUPERVISOR_REVIEW_NONE,
    SUPERVISOR_REVIEW_REQUIRED,
    coerce_supervisor_review,
)

log = logging.getLogger(__name__)

#: The ``afk`` overlay, the v2 home of the retired ``walk_away`` boolean
#: (ADR-0022 D-6 keeps the overlay itself untouched).
AFK_OVERLAY = "afk"

#: Base-preset names that no longer select anything (ADR-0022 D-1).
#: ``adaptive`` is the sole shipped baseline and is therefore not written
#: into a v2 entry either — naming the only posture says nothing — so all
#: three are dropped. A name outside this set is a *user-defined* preset
#: from ``friction-presets.yaml``: a real selection, preserved verbatim.
RETIRED_PRESETS = ("strict", "guided", BASELINE_PRESET)

#: v1 keys a migrated entry no longer carries. ``friction_level`` is the
#: one that must go: left behind as ``strict`` it names a retired preset
#: that post-GH-1162 resolution has to reject rather than quietly resolve
#: at the more autonomous baseline.
_RETIRED_KEYS = ("friction_level", "walk_away", "human_review")


def _load_document(path: Path) -> dict[str, Any]:
    """Tolerantly load a YAML mapping, degrading to ``{}`` on any failure.

    Mirrors ``session_yaml._load_yaml_mapping`` rather than importing it:
    a migration that crashed on an already-corrupt store would leave the
    user with no way forward, and the *unfiltered* document is needed
    here — ``FrictionYamlDocument``'s readers drop everything outside the
    durable key set, including each entry's ``match`` globs.
    """
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, ValueError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


@dataclass(frozen=True)
class EntryMigration:
    """What one ``defaults:`` block or ``projects[]`` entry changed to."""

    scope: str
    supervisor_review: str
    added_overlays: list[str] = field(default_factory=list)
    dropped_keys: list[str] = field(default_factory=list)
    dropped_preset: str | None = None

    @property
    def changed(self) -> bool:
        return bool(self.added_overlays or self.dropped_keys or self.dropped_preset)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "supervisor_review": self.supervisor_review,
            "added_overlays": list(self.added_overlays),
            "dropped_keys": list(self.dropped_keys),
            "dropped_preset": self.dropped_preset,
        }


def _preset_asks_for_more_oversight(prefs: dict[str, Any]) -> bool:
    """Did the v1 posture name a preset stricter than the baseline?

    ``strict`` and ``guided`` both existed to make MORE gates fire than
    ``adaptive`` did (ADR-0016 D-9/D-10). A repo carrying either was
    asking for oversight, so the migration honours that over a stale
    ``human_review: false`` sitting in the same entry — the ticket's
    mapping table reads "``gate_preset: strict`` (any) → required".
    Failing that direction is the whole point of this module.
    """
    named = prefs.get("gate_preset")
    if not isinstance(named, str):
        named = prefs.get("friction_level")
    if not isinstance(named, str):
        return False
    return named.strip().lower() in ("strict", "guided")


def resolve_supervisor_review(prefs: dict[str, Any]) -> str:
    """Map a v1 (or already-v2) prefs mapping to a ``supervisor_review`` pole.

    Precedence, most explicit first:

    1. an existing ``supervisor_review`` — already v2, coerced (so a
       malformed value there still reads ``required``);
    2. a ``strict`` / ``guided`` preset — an explicit request for more
       oversight, which outranks a stale ``human_review`` in the same
       entry;
    3. a real boolean ``human_review`` — ``False`` is the ONLY input
       that produces ``none``, matching ADR-0019's polarity;
    4. everything else — absent, unset, malformed, or a preset this
       function does not recognise — ``required``.
    """
    if "supervisor_review" in prefs:
        return coerce_supervisor_review(prefs["supervisor_review"])
    if _preset_asks_for_more_oversight(prefs):
        return SUPERVISOR_REVIEW_REQUIRED
    review = prefs.get("human_review")
    if review is False:
        return SUPERVISOR_REVIEW_NONE
    return SUPERVISOR_REVIEW_REQUIRED


def _overlays_for(prefs: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return ``(overlays, added)`` — the v2 overlay list and what this added.

    Mirrors :func:`dev10x.domain.gate_policy.legacy_session_mapping`, the
    seam GH-1162 removes: ``solo-maintainer`` in ``active_modes`` and
    ``walk_away: true`` both named overlays that only the legacy
    translation produced. Materialising them keeps the posture the repo
    already resolved to; ``active_modes`` itself is left in place, since
    it is a playbook/DoD axis this migration does not own.
    """
    declared = prefs.get("gate_overlays")
    overlays = [str(overlay) for overlay in declared] if isinstance(declared, list) else []
    added: list[str] = []
    modes = prefs.get("active_modes")
    if isinstance(modes, list) and SOLO_OVERLAY in modes and SOLO_OVERLAY not in overlays:
        overlays.append(SOLO_OVERLAY)
        added.append(SOLO_OVERLAY)
    if prefs.get("walk_away") is True and AFK_OVERLAY not in overlays:
        overlays.append(AFK_OVERLAY)
        added.append(AFK_OVERLAY)
    return overlays, added


def migrate_prefs(prefs: dict[str, Any], *, scope: str) -> tuple[dict[str, Any], EntryMigration]:
    """Return the v2 form of one prefs mapping plus a record of what changed.

    Pure: no I/O, so both stores and every test share one implementation
    of the mapping table. Keys outside the durable set (notably
    ``match``) are preserved untouched and in position.
    """
    migrated = dict(prefs)
    review = resolve_supervisor_review(prefs)
    migrated["supervisor_review"] = review

    overlays, added = _overlays_for(prefs)
    if overlays:
        migrated["gate_overlays"] = overlays

    dropped_preset: str | None = None
    named = migrated.get("gate_preset")
    if isinstance(named, str) and named.strip().lower() in RETIRED_PRESETS:
        dropped_preset = named
        del migrated["gate_preset"]

    dropped = [key for key in _RETIRED_KEYS if key in migrated]
    for key in dropped:
        del migrated[key]

    return migrated, EntryMigration(
        scope=scope,
        supervisor_review=review,
        added_overlays=added,
        dropped_keys=dropped,
        dropped_preset=dropped_preset,
    )


def _needs_migration(prefs: dict[str, Any]) -> bool:
    """Is this mapping still v1-shaped?

    The idempotency predicate: a mapping already carrying
    ``supervisor_review`` and none of the retired keys or preset names is
    left byte-identical, so a second run reports nothing.
    """
    if "supervisor_review" not in prefs:
        return True
    if any(key in prefs for key in _RETIRED_KEYS):
        return True
    named = prefs.get("gate_preset")
    if isinstance(named, str) and named.strip().lower() in RETIRED_PRESETS:
        return True
    return False


def _migrate_document(doc: dict[str, Any]) -> tuple[dict[str, Any], list[EntryMigration]]:
    """Migrate a whole ``friction.yaml`` mapping in memory."""
    updated = dict(doc)
    records: list[EntryMigration] = []

    defaults = updated.get("defaults")
    if isinstance(defaults, dict) and _needs_migration(defaults):
        migrated, record = migrate_prefs(defaults, scope="defaults")
        updated["defaults"] = migrated
        records.append(record)

    projects = updated.get("projects")
    if isinstance(projects, list):
        rebuilt: list[Any] = []
        for index, entry in enumerate(projects):
            if not isinstance(entry, dict) or not _needs_migration(entry):
                rebuilt.append(entry)
                continue
            scope = f"projects[{index}]"
            match = entry.get("match")
            if isinstance(match, list) and match:
                scope = f"projects[{index}] {match[0]}"
            migrated, record = migrate_prefs(entry, scope=scope)
            rebuilt.append(migrated)
            records.append(record)
        updated["projects"] = rebuilt

    return updated, records


def _migrate_friction_yaml(*, path: Path | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Migrate the global ``friction.yaml`` in place (ADR-0011 write safety).

    The read-modify-write runs under :func:`file_lock` on the store's own
    ``friction.yaml.lock`` sidecar — the same sidecar
    :func:`locked_yaml_update` and the sanctioned
    ``upsert_project_prefs`` writer take, so two worktrees migrating
    concurrently exclude each other. The write itself goes through
    :func:`atomic_write_text` via
    :meth:`FrictionYamlDocument.render_document`, which re-prepends the
    canonical header comment; ``locked_yaml_update``'s bare
    ``safe_dump`` would silently strip it from every user's file, and a
    migration is precisely the run where that would go unnoticed.

    Idempotent: a document with nothing left to migrate is not written
    at all, so a second run leaves the file byte-identical.

    ``dry_run`` reports the same per-entry records without writing, so an
    operator can read the posture change before accepting it.
    """
    target = path or Dev10xConfigDir.friction_yaml()
    if not target.exists():
        return {"path": str(target), "migrated": False, "entries": [], "reason": "absent"}
    with file_lock(target):
        doc = _load_document(target)
        updated, records = _migrate_document(doc)
        if not records:
            return {"path": str(target), "migrated": False, "entries": []}
        if not dry_run:
            atomic_write_text(target, FrictionYamlDocument.render_document(updated))
    if not dry_run:
        log.info("migrated %d friction.yaml entries to schema v2", len(records))
    return {
        "path": str(target),
        "migrated": not dry_run,
        "dry_run": dry_run,
        "entries": [record.to_dict() for record in records],
    }


def migrate_friction_yaml(
    *, path: Path | None = None, dry_run: bool = False
) -> Result[dict[str, Any]]:
    """``Result``-wrapped :func:`_migrate_friction_yaml` for MCP/CLI callers."""
    return ok(_migrate_friction_yaml(path=path, dry_run=dry_run))


def _migrate_legacy_repo_config(
    *, toplevel: str, path: Path | None = None, dry_run: bool = False
) -> dict[str, Any]:
    """Fold a repo's legacy ``config.yaml`` posture into ``friction.yaml``.

    The legacy per-repo file is read-only here. ADR-0018 keeps Dev10x
    out of a repo's ``.claude/`` tree, and rewriting the file would not
    help anyway: what has to survive the fallback read being retired is
    the *global* store carrying the repo's posture. So its durable keys
    are mapped to v2 and upserted as a ``projects[]`` entry keyed by the
    repo stem, covering the repo and every worktree of it (GH-855).

    A repo already covered by a ``projects[]`` entry is skipped: that
    entry already shadows the legacy file, so folding it in would
    overwrite live config with a stale one.
    """
    target = path or Dev10xConfigDir.friction_yaml()
    legacy_path = ConfigYamlDocument(toplevel=toplevel).path
    legacy = ConfigYamlDocument(toplevel=toplevel).data()
    prefs = {key: value for key, value in legacy.items() if key in DURABLE_KEYS}
    if not prefs:
        return {"path": str(legacy_path), "migrated": False, "reason": "absent"}
    if FrictionYamlDocument(toplevel=toplevel).matched() is not None:
        return {"path": str(legacy_path), "migrated": False, "reason": "already-covered"}

    migrated, record = migrate_prefs(prefs, scope=f"config.yaml {toplevel}")
    match = match_globs_for_repo(repo_name=repo_stem(Path(toplevel).name))
    if not dry_run:
        with file_lock(target):
            doc = _load_document(target)
            updated = FrictionYamlDocument.with_project(
                doc, match=match, prefs=migrated, supersedes=[toplevel]
            )
            atomic_write_text(target, FrictionYamlDocument.render_document(updated))
        log.info("folded legacy config.yaml for %s into friction.yaml", toplevel)
    return {
        "path": str(legacy_path),
        "migrated": not dry_run,
        "dry_run": dry_run,
        "match": match,
        "entries": [record.to_dict()],
    }


def migrate_legacy_repo_config(
    *, toplevel: str, path: Path | None = None, dry_run: bool = False
) -> Result[dict[str, Any]]:
    """``Result``-wrapped :func:`_migrate_legacy_repo_config` for MCP/CLI callers."""
    return ok(_migrate_legacy_repo_config(toplevel=toplevel, path=path, dry_run=dry_run))


def migrate_configs(
    *, toplevel: str | None = None, path: Path | None = None, dry_run: bool = False
) -> Result[dict[str, Any]]:
    """Migrate both durable stores, reporting what changed per entry.

    The global store is migrated first so the legacy fold sees v2 entries
    when it probes for an already-covered repo.

    ``pending`` is the count of entries this run would change (or did),
    so a caller reads one number rather than inferring from ``migrated``,
    which is ``False`` under ``dry_run`` even when work is outstanding.
    """
    report: dict[str, Any] = {"friction_yaml": _migrate_friction_yaml(path=path, dry_run=dry_run)}
    if toplevel:
        report["legacy_config_yaml"] = _migrate_legacy_repo_config(
            toplevel=toplevel, path=path, dry_run=dry_run
        )
    report["pending"] = sum(
        len(part.get("entries", ())) for part in report.values() if isinstance(part, dict)
    )
    report["dry_run"] = dry_run
    return ok(report)


__all__ = [
    "AFK_OVERLAY",
    "RETIRED_PRESETS",
    "EntryMigration",
    "migrate_configs",
    "migrate_friction_yaml",
    "migrate_legacy_repo_config",
    "migrate_prefs",
    "resolve_supervisor_review",
]
