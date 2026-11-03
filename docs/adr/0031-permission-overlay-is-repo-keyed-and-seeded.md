# ADR-0031: Where the repo-scoped permission overlay lives

- **Status:** Proposed (awaiting supervisor decision)
- **Date:** 2026-09-27; refreshed 2026-11-03 against `a3ea3142`
- **Supersedes:** none
- **Amends:** ADR-0025 § 4 under Options E and F (A keeps it as
  written). Answers the four questions ADR-0025 § Consequences left open
- **Related:** GH-1313, GH-1471, GH-1677, GH-1673, GH-1493, GH-1405,
  GH-1666, ADR-0018, ADR-0021, ADR-0026, ADR-0028

## Context

GH-1313 couples two questions. **Q1**, which catalog is authoritative,
is settled: ADR-0025 names `skills/upgrade-cleanup/projects.yaml`.
**Q2**, where user customisation lives, got a one-paragraph answer in
ADR-0025 § 4 (a `permissions:` block in `friction.yaml` `projects[]`)
that was never specified or built.

### What changed since the 2026-09-27 draft

The first draft of this ADR recommended that `friction.yaml` block.
Before anyone decided, GH-1677 shipped a **different** store:

- `~/.config/Dev10x/granted-permissions.yaml`
  (`granted_catalog.py:7-16`). Dev10x owns the whole file. It holds one
  key, `base_permissions` (`:31`), so it is **global and allow-only**.
- Written only by `permission_grant(remember=true)`, after triage
  (`grant.py:761`), which refuses unknown executables (GH-1687) and
  interpreter-runs-anything grants (GH-1723).
- Merged into the user layer by `load_effective_config`
  (`catalog_load.py:105`), so `ensure_base` and `seed_worktree`
  (`catalog_write.py:790`, `:1160`) deliver it to every checkout,
  including ones created later.

GH-1673 added `sync_main_to_worktrees`
(`merge_worktree_permissions.py:346`), which copies the main checkout's
rules to existing worktrees while filtering checkout-pinned ones
(`pins_a_checkout`, `:322`). GH-1493 added the first per-repo
*validator* key to `friction.yaml` (`dx017`), with an
`effective(fallback_toplevels=…)` probe of worktree first and main
checkout second (`friction_yaml.py:193`).

So the question is no longer "build an overlay"; a global allow tier
exists. It is: **is a repo-scoped tier needed on top of it, and if so,
which file holds it?**

### Facts verified for this refresh

| Fact | Evidence |
|---|---|
| `friction.yaml` writes lose comments | every writer renders through `yaml.safe_dump` (`friction_yaml.py:320-327`) |
| Repo-stem globs miss herdr-style worktrees | `match_globs` tests the full path and its basename (`:117-125`). `/work/.herdr/worktrees/<repo>/<slug>` matches neither `*/<repo>` nor `*/<repo>-*` |
| Seeding's per-repo reads have no main-checkout fallback | `tracker_resolve.py:31,51` and `ide_resolve.py:31,46` call `matched()` only |
| Reaping does not touch repo-stem pins | `reap_dead_projects` drops only entries whose absolute paths are all gone (`:601-634`) |
| Asks are still suppressible | `SUPPRESSION_REFUSED_KEYS` holds only the three deny keys (`catalog_merge.py:83`) |
| `merge-worktree`'s verdict is still Python literals and binary | `NOISE_PATTERNS` `:43`, `BASH_INNER_NOISE_PATTERNS` `:67`, `GENERALIZE_PATTERNS` `:77` |

## Options

### Option A: repo tier in `friction.yaml` `projects[].permissions`

`granted-permissions.yaml` stays the global allow tier. A
`permissions:` block (`allow` / `remove` / `deny` / `ask` /
`local_only`) joins the matching `projects[]` entry, folded in
`render_catalog` (`catalog_write.py:761`) beside the tracker and IDE
blocks (`:768`, `:773`). `remember` gains `scope=global|repo`.

- **+** One file for every per-repo fact. Seeding already reads it twice
  for tracker and IDE. GH-1493 just set the "per-repo policy goes in
  `friction.yaml`" precedent. Matches ADR-0025 § 4 and ADR-0026
  § Prerequisites as accepted, so no ADR is amended.
- **+** Reuses `pin_project_prefs` (`preset_pin.py:264`), with its lock,
  supersede and carry-forward logic.
- **−** Prerequisites that do not exist: a list-union writer
  (`pin_project_prefs` replaces keys), `permissions` in `_DURABLE_KEYS`,
  and a main-checkout fallback in the tracker and IDE resolvers. Without
  the fallback, herdr worktrees silently get no overlay.
- **−** Every `remember(scope=repo)` rewrites a hand-annotated file and
  strips its comments. GH-1677 chose its own file to avoid exactly this.
- **−** First-match-wins resolution suits scalars. Rule lists need union
  semantics across a repo entry and a narrower worktree entry.

### Option E: repo tier in `granted-permissions.yaml`, keyed by exact repo identity

Extend the Dev10x-owned file with
`repos: {<identity>: {allow, remove, deny, ask, local_only}}`. The key
comes from `resolve_repo_identity` (`preset_pin.py:100`), which reads the
git common dir. No globs. `task_index_yaml` (`dev10x_paths.py:157`) is
the precedent for an exact-identity, Dev10x-owned per-repo store.
`friction.yaml` stays selectors and gate policy only.

- **+** The common-dir key covers every worktree, wherever it lives, with
  no fallback probe. That fixes the herdr gap by construction.
- **+** Rewrites are lossless by contract (`granted_catalog.py:12-16`),
  and the file already has a locked, idempotent writer and one merge
  seam.
- **+** One file answers "why is this rule allowed?": the global and
  repo tiers sit side by side.
- **−** Amends accepted ADR-0025 § 4 and ADR-0026 § Prerequisites.
- **−** Basename collisions (`/a/api`, `/b/api`) share one section.
  `task_index_yaml` shares this weakness today. Keying by root fails for
  bare repos (`preset_pin.py:124`).
- **−** Users cannot keep comments on why a repo denies something. The
  name "granted" fits allow better than deny; renaming needs an ADR-0028
  window.
- **−** Only cleaner than A if it never accepts globs. A `match:` list
  here would be the second resolver ADR-0026 warns about.

### Option F: no repo tier; the global triaged allow layer is the answer

Declare GH-1677's layer the Q2 answer. Triage, not location, keeps unsafe
rules out. Project-only rules stay in their checkout's
`settings.local.json`. User `remove` / `deny` / `ask` stay in the
userspace `projects.yaml` (ADR-0021 merge).

- **+** Zero new schema; it ratifies shipped, tested code. A grant
  already writes global settings (`utility_tools.py:197-198`), so a
  global memory has the same scope as the grant itself.
- **+** Meets two of GH-1313's four acceptance items outright: upgrades
  flow and nothing writes the shipped catalog.
- **−** Rules that are safe in one repo travel to all of them.
  `make test` derives `Bash(make:*)`, which then reaches a repo with a
  `make deploy` recipe.
- **−** No memory of a "stays here" verdict, so "the classifier does not
  re-ask" holds only as far as triage's shape tests stay deterministic.
- **−** No repo-scoped `deny`. A stricter repo hand-edits
  `settings.local.json`, the per-checkout source of truth GH-1100 E22
  saw fail.
- **−** The harness's own "Don't ask again" still reaches only one
  checkout. F covers only approvals routed through `permission_grant`.

Retired from the first draft: **B** (a `match:` section in the userspace
`projects.yaml`, a second glob resolver) and **C** (fan out
`settings.local.json`, a source of truth that dies with its checkout).
Neither gained support from the new code.

## Ranking

The evaluation ranks **E, then A, then F**, with **medium** confidence.
The decision is the supervisor's.

- E and A both meet all four GH-1313 acceptance items. E gets there with
  fewer prerequisites, and avoids two defects verified above: comment
  loss and the herdr glob gap.
- A's case is cohesion, with one per-repo file and no ADR amendments.
  It is the better pick if keeping `friction.yaml` as the single
  per-repo home matters more than those two defects.
- F is a legitimate **defer**: ratify what shipped and let GH-1471's
  ledger show whether cross-repo leakage actually hurts. Its ledger has
  five rows so far, and none of them is a cross-repo leak.

## Open questions (independent of A / E / F unless noted)

1. **Should asks be non-suppressible?** The proposal is to add
   `base_asks` to `SUPPRESSION_REFUSED_KEYS`. Today a user `remove:` can
   silence an ask.
2. **`local_only` memory (A or E only).** It needs a key, and
   `merge-worktree` needs the three-tier verdict (local-only / project /
   global-candidate), with global-candidate kept proposal-only.
3. **Existing userspace forks.** They keep working under ADR-0021.
   `permission doctor` offers to move `user_only` rules into the chosen
   tier, under an ADR-0028 `config` window.
4. **Divergence reporting.** `catalog-diff --strict` stays the detector
   and learns the new tier. `plugin-doctor` wraps it per worktree.
5. **GH-1313 step 2 classes.** Confirm R / X / W as not-seeded, and
   decide D (state-changing git) and L (raw linters and test runners).
   Unchanged from the first draft.

## Consequences

- **A:** `friction.yaml` carries permissions as well as gate policy. The
  tracker and IDE resolvers gain the fallback as a side benefit. Grants
  rewrite a hand-edited file.
- **E:** ADR-0025 § 4 and ADR-0026 § Prerequisites are amended to point
  at `granted-permissions.yaml`. `friction.yaml` stays selector-only.
  Two stores are keyed by repo identity rather than globs.
- **F:** ADR-0025 § 4 is amended to name the global layer. This ADR is
  then Accepted with no code change, and repo scope is revisited only on
  ledger evidence.
- **All:** `CatalogDrift` gains the new layer as an input, so GH-1100's
  three provenance states become reportable.

## References

- `src/dev10x/core/skills/permission/granted_catalog.py:7-16, 31, 69`
- `src/dev10x/core/skills/permission/catalog_load.py:94-108`
- `src/dev10x/core/skills/permission/catalog_write.py:652, 705, 761-773, 790, 1160`
- `src/dev10x/core/skills/permission/catalog_merge.py:83, 336`
- `src/dev10x/core/skills/permission/merge_worktree_permissions.py:43, 67, 77, 322, 346`
- `src/dev10x/core/skills/permission/grant.py:761`
- `src/dev10x/core/skills/permission/tracker_resolve.py:31, 51`,
  `ide_resolve.py:31, 46`
- `src/dev10x/core/domain/documents/friction_yaml.py:101-126, 193, 320-327, 601-634`
- `src/dev10x/core/session/preset_pin.py:100, 264`
- [ADR-0021](0021-permission-catalog-merges-rather-than-shadows.md),
  [ADR-0025](0025-projects-yaml-is-the-authoritative-permission-catalog.md),
  [ADR-0026](0026-projects-match-names-its-addressing-scheme.md),
  [ADR-0028](0028-deprecations-carry-a-removal-version.md)
- [GH-1313](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1313),
  [GH-1471](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1471),
  [GH-1677](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1677)
