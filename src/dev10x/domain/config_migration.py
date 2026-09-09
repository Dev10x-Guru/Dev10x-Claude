"""One-shot v1 → v2 durable-config migration (GH-1166, ADR-0022).

Every durable config written before ADR-0022 names its posture in v1
vocabulary — ``gate_preset`` / ``friction_level`` selecting one of three
shipped postures, ``human_review`` as a boolean, ``walk_away`` as a
separate flag. Those shapes used to resolve only because a read-compat
seam in ``gate_policy`` and the ``GateResolutionQuery.run`` fallback
translated them. GH-1162 retired that seam — an un-migrated config is now
refused by name rather than resolved — so this module is the ONLY thing
that still reads v1 vocabulary, and the only way forward for a store that
still carries it.

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
    SessionYamlDocument,
    match_globs_for_repo,
    repo_stem,
)
from dev10x.domain.file_locks import atomic_write_text, file_lock
from dev10x.domain.gate_policy import (
    BASELINE_PRESET,
    MIGRATOR_COMMAND,
    RETIRED_PRESET_NAMES,
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
RETIRED_PRESETS = (*RETIRED_PRESET_NAMES, BASELINE_PRESET)

#: v1 keys a migrated entry no longer carries. ``friction_level`` is the
#: one that must go: left behind as ``strict`` it names a retired preset
#: that post-GH-1162 resolution has to reject rather than quietly resolve
#: at the more autonomous baseline.
_RETIRED_KEYS = ("friction_level", "walk_away", "human_review")

try:  # pragma: no cover — exercised by whichever branch the wheel provides
    #: libyaml-backed loader, ~5-10x faster than the pure-Python one. This
    #: module is read on the SessionStart path by :func:`schema_v2_pending`,
    #: where a ~19KB store costs ~13ms under the Python loader — enough to
    #: matter against a hook budget in the tens of milliseconds (GH-1252).
    #: PyYAML's manylinux/macOS wheels bundle libyaml, so the fallback is
    #: rare; when it is taken the only consequence is the slower parse the
    #: code had before, never a different result.
    from yaml import CSafeLoader as _SafeLoader
except ImportError:  # pragma: no cover — pure-Python PyYAML build
    from yaml import SafeLoader as _SafeLoader  # type: ignore[assignment]


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
        data = yaml.load(path.read_text(), Loader=_SafeLoader)
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

    Replays what the read-compat seam GH-1162 removed: ``solo-maintainer``
    in ``active_modes`` and ``walk_away: true`` both named overlays that
    only the legacy translation produced. Materialising them keeps the posture the repo
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


def _has_v1_residue(prefs: dict[str, Any]) -> bool:
    """Does this mapping still carry retired v1 vocabulary?

    Split out of :func:`_needs_migration` (GH-1252) so the SessionStart
    banner and the migrator share one definition of "stale". The two
    previously used unrelated predicates, which is how a machine could be
    told to "migrate config files" it did not need to migrate.

    Deliberately narrower than :func:`_needs_migration`: a mapping merely
    *missing* ``supervisor_review`` is not v1 residue — nothing retired
    survives in it, and :func:`coerce_supervisor_review` already reads an
    absent value as the safe ``required`` pole. The migrator still makes
    it explicit; the banner must not nag about it, because there is no
    stale vocabulary for the operator to act on.

    The ``active_modes`` leg mirrors :func:`gate_policy.legacy_policy_keys`
    exactly, and closes the sharpest half of GH-1252: that function
    REFUSES gate resolution when ``solo-maintainer`` sits in
    ``active_modes`` without also being in ``gate_overlays``, while this
    predicate did not inspect ``active_modes`` at all. A store in that
    shape was therefore "already at schema v2" to the migrator and
    unresolvable to every gate — an error naming a remedy that no-ops.
    Note the second half of the condition: a migrated store states the
    posture in BOTH places (the migrator materialises the overlay and
    leaves the mode alone, ADR-0022 D-6), so this fires only on the
    genuinely half-migrated shape and never on a healthy one.
    """
    if any(key in prefs for key in _RETIRED_KEYS):
        return True
    modes = prefs.get("active_modes")
    overlays = prefs.get("gate_overlays")
    if isinstance(modes, list) and SOLO_OVERLAY in modes:
        if not isinstance(overlays, list) or SOLO_OVERLAY not in overlays:
            return True
    named = prefs.get("gate_preset")
    return isinstance(named, str) and named.strip().lower() in RETIRED_PRESETS


def _needs_migration(prefs: dict[str, Any]) -> bool:
    """Is this mapping still v1-shaped?

    The idempotency predicate: a mapping already carrying
    ``supervisor_review`` and none of the retired keys or preset names is
    left byte-identical, so a second run reports nothing.
    """
    return "supervisor_review" not in prefs or _has_v1_residue(prefs)


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


def schema_v2_pending(*, path: Path | None = None) -> int:
    """Count durable ``friction.yaml`` entries carrying v1 residue (GH-1252).

    A read-only, lock-free counterpart to :func:`migrate_configs` for the
    one caller that must not pay for a full migration walk: the
    SessionStart banner runs on every session, and
    :func:`_migrate_friction_yaml` takes the store's write lock and
    builds an ``EntryMigration`` record per entry even under ``dry_run``.
    Both this and the migrator judge staleness with
    :func:`_has_v1_residue`, so the banner and the remedy it names cannot
    disagree — they previously used unrelated predicates, which is how a
    machine could be told to "migrate config files" that needed no
    migration, and equally could be told nothing while genuinely stale.

    **Cost.** This parses the store, on every session. An earlier draft
    skipped the parse when no retired key appeared in the raw bytes, but
    that optimization was dead on arrival: the ``active_modes`` leg of
    :func:`_has_v1_residue` forces ``active_modes`` into the marker set,
    and that key is present in virtually every real entry — so the scan
    always matched and always parsed anyway, while the docstring and
    benchmark claimed a saving that no longer existed. The parse is
    instead made cheap at the source: :func:`_load_document` uses the
    libyaml loader, which takes the ~19KB reference store from ~13ms to
    ~2ms. ``tests/benchmarks`` ``session-start-schema-scan`` pins the
    number so a regression is caught by the CI backpressure gate rather
    than by a user's session-start latency.

    A read failure reports 0 — the banner's job is to add a sentence, not
    to deny a session — but a store that exists and cannot be read is
    logged, since silently reporting "nothing stale" for a store nobody
    could open is the same blind spot this function exists to remove. An
    absent store is normal (a fresh install) and stays quiet.

    Scoped to the global store deliberately. The legacy per-repo fold
    needs a ``toplevel`` and probes a second file; the banner is a
    userspace-wide signal and must stay independent of which repo a
    session happens to start in.
    """
    target = path or Dev10xConfigDir.friction_yaml()
    if not target.exists():
        return 0
    # Deliberately NOT `_load_document`: that helper collapses "absent",
    # "unreadable" and "empty" into one `{}`, which is right for the
    # migrator but would either warn about a harmless empty file or stay
    # silent about an unreadable one. The banner needs those apart.
    try:
        text = target.read_text()
    except (OSError, ValueError) as exc:
        # ValueError covers UnicodeDecodeError on a non-UTF-8 store, which
        # is not an OSError and would otherwise escape into the hook.
        log.warning(
            "could not read %s for the schema-staleness check (%s); reporting "
            "nothing pending. Run `%s --dry-run` to check by hand.",
            target,
            exc,
            MIGRATOR_COMMAND,
        )
        return 0
    try:
        data = yaml.load(text, Loader=_SafeLoader)
    except yaml.YAMLError as exc:
        log.warning(
            "could not parse %s for the schema-staleness check (%s); reporting "
            "nothing pending. Run `%s --dry-run` to check by hand.",
            target,
            exc,
            MIGRATOR_COMMAND,
        )
        return 0
    doc = data if isinstance(data, dict) else {}
    if not doc:
        return 0
    raw_defaults = doc.get("defaults")
    defaults: dict[str, Any] = raw_defaults if isinstance(raw_defaults, dict) else {}
    raw_projects = doc.get("projects")
    entries = raw_projects if isinstance(raw_projects, list) else []

    # Judge each project entry on the MERGED view the resolver actually
    # sees — `_durable()` returns `{**defaults, **matched}` — not on the
    # entry in isolation. Isolated judging over-reports: a store stating
    # `active_modes` in `defaults` and the matching `gate_overlays` in
    # each entry resolves cleanly, yet every entry would be counted
    # stale. A banner that cries wolf is the same defect as one that
    # stays silent, just in the other direction.
    counted: list[dict[str, Any]] = [defaults]
    counted.extend({**defaults, **entry} for entry in entries if isinstance(entry, dict))
    return sum(1 for prefs in counted if prefs and _has_v1_residue(prefs))


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
    """Fold a repo's legacy per-repo posture into ``friction.yaml``.

    The legacy per-repo files are read-only here. ADR-0018 keeps Dev10x
    out of a repo's ``.claude/`` tree, and rewriting them would not help
    anyway: what has to survive the fallback read being retired is the
    *global* store carrying the repo's posture. So their durable keys
    are mapped to v2 and upserted as a ``projects[]`` entry keyed by the
    repo stem, covering the repo and every worktree of it (GH-855).

    **Both** tier-2 files are folded (GH-1252). ``_durable()`` step 2
    reads ``{**session.yaml, **config.yaml}``, but this fold used to see
    only ``config.yaml`` — so a repo whose v1 posture sat in the
    pre-split ``session.yaml`` was unreachable by every migration path
    while still tripping :func:`legacy_policy_keys`, which refuses gate
    resolution and names a migrator that could not fix the file. The
    merge precedence mirrors ``_durable()`` exactly, so folding cannot
    change which value a repo resolves to.

    A repo already covered by a ``projects[]`` entry is skipped: that
    entry already shadows the legacy files, so folding one in would
    overwrite live config with a stale one.
    """
    target = path or Dev10xConfigDir.friction_yaml()
    legacy_path = ConfigYamlDocument(toplevel=toplevel).path
    session_path = SessionYamlDocument(toplevel=toplevel).path
    session_data = _load_document(session_path)
    config_data = ConfigYamlDocument(toplevel=toplevel).data()
    legacy = {**session_data, **config_data}
    prefs = {key: value for key, value in legacy.items() if key in DURABLE_KEYS}
    if not prefs:
        return {"path": str(legacy_path), "migrated": False, "reason": "absent"}
    if FrictionYamlDocument(toplevel=toplevel).matched() is not None:
        return {"path": str(legacy_path), "migrated": False, "reason": "already-covered"}

    # Name the files that actually carried the posture, so an operator
    # reading the report can tell a session.yaml fold from a config.yaml
    # one — they are separate remediation stories (GH-1252). Non-empty
    # `prefs` guarantees at least one contributor, so no fallback is
    # needed here.
    contributing = [
        str(file_path)
        for file_path, data in ((session_path, session_data), (legacy_path, config_data))
        if any(key in DURABLE_KEYS for key in data)
    ]
    scope_files = ", ".join(Path(name).name for name in contributing)
    migrated, record = migrate_prefs(prefs, scope=f"{scope_files} {toplevel}")
    match = match_globs_for_repo(repo_name=repo_stem(Path(toplevel).name))
    if not dry_run:
        with file_lock(target):
            doc = _load_document(target)
            updated = FrictionYamlDocument.with_project(
                doc, match=match, prefs=migrated, supersedes=[toplevel]
            )
            atomic_write_text(target, FrictionYamlDocument.render_document(updated))
        log.info("folded legacy %s for %s into friction.yaml", scope_files, toplevel)
    return {
        "path": str(legacy_path),
        "sources": contributing,
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
    "schema_v2_pending",
]
