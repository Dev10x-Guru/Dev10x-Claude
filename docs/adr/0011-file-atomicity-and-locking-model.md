# 11. File atomicity and locking model

Date: 2026-05-22

## Status

Accepted

## Context

Several files under `~/.claude/` and `<repo>/.claude/session/` are
written concurrently by multiple processes — hook scripts running in
parallel worktrees, the long-lived MCP server, the CLI, and sub-agent
processes. The 2026-05-18 architecture audit (memo 005, milestone M1)
catalogued five HIGH-severity write paths that bypassed the existing
concurrency-safe helpers in `dev10x.domain.file_locks`:

- `domain.session_document.write_state` — bare `path.write_text(...)`
- `plan.service.set_plan_context` / `archive_plan` — `Plan.load() →
  Plan.save()` cycle without `file_lock`
- `hooks.session_dispatch.session_persist` — non-atomic write paired
  with an atomic-rename reader in `session_reload`
- `platform.registry.Registry.add` / `remove` — load → mutate → save
  without serialization
- `hooks.session_policy.MigratePluginPermissionsRule.apply` and other
  multi-file mutators — no cross-file rollback

The audit also flagged that the two lock-file naming conventions in
`file_locks.py` (`.with_suffix(".lock")` vs `_lock_path_for` which
appends `.lock`) are deliberate but undocumented as a hard rule.

## Decision

We adopt a layered atomicity model with explicit guarantees per layer
and a known boundary at the multi-file level.

### Layer 1 — `atomic_write_text` / `atomic_write_bytes`

Every write of a state, plan, settings, or registry file uses
`atomic_write_text` (or `atomic_write_bytes`) so readers never observe
a half-written file. The implementation uses `mkstemp` + `os.fsync` +
`os.rename` in the target's parent directory.

**Required for:** any file whose contents may be read by another
process while we are writing it. This includes single-writer files
because crash safety also matters (process killed mid-write must not
corrupt persisted state).

### Layer 2 — `file_lock(path)`

Every `load → mutate → save` cycle on a shared file holds an exclusive
`fcntl.flock` on a `.lock` sidecar. The lock spans the entire cycle so
two concurrent writers cannot both read the same baseline and overwrite
each other's changes.

**Required for:** `plan.service` (set_plan_context, archive_plan),
`Registry.add` / `Registry.remove`, hook scripts that mutate user
settings files, and any future code that reads state, computes a
delta, and writes it back.

The sidecar is intentionally not unlinked on release: a third writer
arriving between `unlink` and the next `open(O_CREAT)` would receive a
fresh inode and acquire an independent flock, breaking mutual
exclusion.

**Lock acquisition timeout.** `file_lock`, `locked_json_update`, and
`locked_yaml_update` acquire the flock via non-blocking `LOCK_NB`
attempts in a poll loop bounded by a `timeout` parameter (default
`LOCK_TIMEOUT_SECONDS` = 10 s). On expiry they raise
`LockTimeoutError` (a subclass of `OSError`) carrying an actionable
"locked by another process — please try again" message. Without this
guard, a holder wedged in an uninterruptible D-state on a network
filesystem, or a `finally` block that raised before `LOCK_UN`, would
block the caller — and, for the long-lived MCP daemon, its async event
loop — indefinitely with no diagnostic. Callers that genuinely need an
unbounded wait pass `timeout=0` to fall back to a single blocking
`LOCK_EX`.

### Layer 3 — `locked_json_update` / `locked_yaml_update`

Composite helpers that combine layers 1 and 2 in a single context
manager. New code that mutates a single JSON or YAML file should
prefer these over open-coded `file_lock(path)` + `Plan.load/save`
patterns.

### Layer 4 — Multi-file mutations have no cross-file UoW

**This is the known boundary.** `MigratePluginPermissionsRule.apply`
rewrites both `settings.json` and `settings.local.json`. `Registry`
operations may in the future span the registry YAML plus per-platform
config files. We do **not** provide a Unit of Work that rolls back
across files when one of N writes fails.

Implications:

- Each file is locked and written atomically (layers 1 + 2), so a
  failure mid-multi-file-mutation leaves each touched file in a
  consistent individual state.
- However, the *set* of files may be inconsistent — one rewritten
  with new rules and one with old.
- Callers that need cross-file atomicity must either (a) collapse the
  mutation to a single file or (b) implement a custom recovery path
  (e.g. write all changes to a staging dir, then rename a manifest
  pointer).

**Two-pass narrowing (validate-then-write).**
`MigratePluginPermissionsRule.apply` runs a dry-run pass first:
`SettingsDocument.preview_replacements` reads and computes the
migrated content for every targeted file *without writing*, so a
parse failure (the common case — a hand-edited corrupt
`settings.local.json`) is detected before any file is written. The
apply pass then calls `SettingsDocument.apply_replacements` per file,
which re-reads and re-migrates the file *under `file_lock`* rather
than persisting the dry-run's precomputed content (GH-825). An edit
landing between the preview and the write is therefore re-migrated,
not clobbered — the single-file lost-update window is closed and the
migrated count reflects the locked apply, not the stale preview. What
remains uncovered is only cross-file atomicity: a genuine write-time
I/O error (disk full, `EACCES`) on file 2 can still leave file 1
already migrated, since each file locks independently.

We accept this boundary because:

1. The current call sites have natural retry semantics — the next
   session-start hook re-runs the migration and converges.
2. A general cross-file transaction abstraction (write-ahead log,
   2PC) would dwarf the value it delivers given the cardinality
   (≤ 3 files per mutation) and frequency (once per session start /
   user action) of our multi-file mutators.
3. The `mkstemp` + `rename` primitive on POSIX is the strongest
   atomic primitive the standard library exposes; building above it
   without a transaction service buys little.

### Sidecar naming convention

Two functions in `file_locks.py` use different sidecar naming:

- `file_lock` and `locked_yaml_update` **append** `.lock` to the full
  target name (`plan.yaml` → `plan.yaml.lock`) via `_lock_path_for`.
- `locked_json_update` **replaces** the target suffix (`settings.local.json`
  → `settings.local.lock`).

The split is deliberate for backward compatibility with on-disk
sidecars created by the permission-skill call sites. New code MUST
use `file_lock` / `locked_yaml_update` (the append convention).
`locked_json_update` is frozen for its existing callers; do not
introduce new call sites.

The two helpers must never target the same path because their lock
sidecars resolve to different files. The module docstring documents
this; the `tests/domain/test_file_locks.py` test asserts the split
empirically for the known caller paths.

## Consequences

### Positive

- A SessionStart reader can never observe a partially written session
  state file: the read side (`claim_state_file`) does an atomic rename
  before reading, and the write side (`write_state`) now does an
  atomic rename before publishing.
- Two concurrent `TaskCreate` hooks or two concurrent
  `set_plan_context` calls cannot lose task entries or context keys —
  the lock serializes them at the plan-file granularity.
- Two parallel `Registry.add(...)` calls cannot lose platform
  registrations.
- The cross-file UoW gap is explicit, scoped, and documented so
  future contributors do not assume atomicity beyond what we
  actually provide.

### Negative

- A crash between the writes of file A and file B in a multi-file
  mutator leaves the set inconsistent. Mitigated by idempotent
  re-execution on the next hook firing.
- Lock contention is theoretically possible if a long-running
  operation holds `file_lock` on a hot path. In practice the
  load → mutate → save cycles are sub-millisecond, and the
  acquisition timeout (default 10 s) converts a wedged holder into a
  surfaced `LockTimeoutError` rather than an indefinite hang.

### Migration

The five HIGH-severity findings (E2/E8 atomic state writes, E3 plan
locks, D1 hook→domain inversion, A12 multi-file locks) ship in
GH-240. No data migration is required — the on-disk sidecar layout
is unchanged.

## References

- Audit memo: `docs/memos/005-2026-05-18-architecture-audit.md`
- Implementation module: `src/dev10x/domain/file_locks.py`
- Tracking ticket: GH-240
