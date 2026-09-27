# ADR-0031: The permission overlay is repo-keyed, and seeding reads it

- **Status:** Proposed (awaiting supervisor decision; recommendation
  below is Option A)
- **Date:** 2026-09-27
- **Supersedes:** none
- **Amends:** ADR-0025 § 4 (specifies the overlay it names), and
  answers the four questions ADR-0025 § Consequences left open
- **Related:** GH-1313, GH-1471, GH-1405, GH-1249, GH-1136, GH-1325,
  ADR-0021, ADR-0026, ADR-0028

## Context

GH-1313 couples two questions. **Q1** asks which catalog is
authoritative. ADR-0025 answered it: `skills/upgrade-cleanup/projects.yaml`,
the catalog on the write path. **Q2** asks where user customisation lives.
ADR-0025 § 4 gave a one-paragraph answer, a `permissions:` block in the
matching `projects[]` entry of `~/.config/Dev10x/friction.yaml`, but it
never specified the block. It also left four questions open. GH-1471
has since opened a tracker to collect field evidence for building Q2.

This ADR does not reopen Q1. It covers the part of Q2 that is still
undecided.

### Current state (at `58158b98`)

| Concern | Where it lives | What is missing |
|---|---|---|
| Shipped ⊕ user merge | `catalog_merge.merge_catalogs` (`catalog_merge.py:334`), ADR-0021 | Nothing is keyed by repo: `rg "match\|projects\|repo" catalog_merge.py` finds only docstring prose, so every root gets the same catalog |
| Deny floor | `SUPPRESSION_REFUSED_KEYS` (`catalog_merge.py:81`) refuses a user suppression of `base_denies`, `tracker_denies` and `ide_denies` (GH-1249 `d0383e2d`, GH-1311 `deb34a29`) | Nothing covers `base_asks` |
| Seeding | `seed_worktree` delegates to `ensure_base` (`catalog_write.py:995-1053`, GH-1405 `a62b3859`) and passes `toplevel=` | `ensure_base` has the checkout's toplevel but reads no per-repo data |
| Overlay store | `friction.yaml` `projects[]`, written by `pin_project_prefs` (`session/preset_pin.py:264`), identity from `resolve_repo_identity` (`:100`) via the git common dir | `rg permissions src/dev10x/domain/documents/friction_yaml.py` finds nothing, so the block does not exist |
| Worktree sync | `merge_worktree_permissions.merge_permissions` (`:219-275`) | Merges into the **main checkout's** `settings.local.json` only (`:225`). The regex lists at `:33`, `:57` and `:67` are Python literals. The verdict is binary: noise or merge |
| Provenance | `provenance.RuleProvenance` (`provenance.py:25`) | `classify_provenance` (`:33`) matches exact strings, and nothing routes on it |
| Grouped-catalog debt | `baseline_coverage.UNTRIAGED_BACKLOG` (`baseline_coverage.py:119`) | **185** rules at this SHA (199 quoted entries minus 14 `OPT_IN_GROUPS`), down from 189 |

GH-1471's evidence ledger is still empty. The layer taxonomy it
proposes is catalog / seed / overlay / local / matcher / hook / doctor.
It frames what this ADR must make expressible: an approval given once
holds in every worktree of the repo, shipped defaults keep flowing, and
project-only noise never reaches global settings.

## Options

### Option A: overlay in `friction.yaml` `projects[]`, and `ensure_base` folds it (ADR-0025 § 4 as written)

Add a `permissions:` block to the matching `projects[]` entry:

```yaml
permissions:
  allow:      [...]   # added over the merged catalog
  remove:     [...]   # suppress a shipped allow (never a deny or ask)
  deny:       [...]
  ask:        [...]
  local_only: [...]   # recorded "stays here" verdicts; never seeded
```

`ensure_base` already receives `toplevel`. It resolves the matching
entry through `FrictionYamlDocument(toplevel=…).matched()`, falling back
to the repo root the way `_policy_toplevel` does in
`mcp/gate_query.py:65-104` (GH-978). It then applies
`shipped ⊕ userspace_additions ⊕ overlay.allow ⊖ overlay.remove`, with
`remove` refused on deny and ask keys. Because `seed_worktree` delegates
to `ensure_base`, sync becomes a property of seeding: a worktree created
tomorrow gets today's approvals.

- **+** It reuses a writer that already locks and upserts idempotently,
  and a repo identity that already covers every worktree. ADR-0026 kept
  `match:` path-addressed precisely so this overlay could build on it.
- **+** Upgrades deliver new shipped rules with no manual merge, because
  the overlay holds only deltas.
- **−** `friction.yaml` then carries two concerns, gate policy and
  permissions, in one entry.
- **−** `catalog_merge` must learn a second source. Until it does,
  `catalog-diff --strict` cannot see overlay drift.

### Option B: a per-repo section inside the userspace `projects.yaml`

Add `projects: [{match: …, allow: …, remove: …}]` to
`~/.config/Dev10x/projects.yaml`, beside the ADR-0021 user additions.

- **+** Permission data stays in the permission catalog file, and
  `catalog_merge` extends in place.
- **−** It is a second `projects[].match` resolver, the exact
  proliferation ADR-0026 documents across four files. It needs its own
  repo-identity code, or a copy of the `friction.yaml` one.
- **−** It contradicts the accepted ADR-0025 § 4 and ADR-0026
  § Prerequisites, so both would need amending.

### Option C: no new store; fan `merge-worktree` out to siblings

Keep each `settings.local.json` authoritative (GH-1100 T6: the
supervisor hand-edits them). Extend `merge_permissions` to write the
union into every registered worktree, and have `seed_worktree` copy the
main checkout's file.

- **+** Smallest change. No schema.
- **−** The source of truth is a file that dies with its checkout.
  GH-1100 E22 recorded worktrees starting from a blank slate while the
  main checkout held 1000+ rules, and a copy-from-main design turns that
  asymmetry into the mechanism.
- **−** There is no place to record `local_only`, so the classifier
  re-asks forever. GH-1471's acceptance forbids that.

### Option D: status quo, documented

- **−** GH-1313's acceptance ("approved once, in force in every
  worktree") stays unmet. Listed for completeness.

## Recommendation

**Option A.** It is the only option that meets GH-1471's framing
without a second repo-matching resolver, and the plumbing it needs
already exists at `ensure_base(toplevel=…)`. Options B and C each
reintroduce a failure this repo has already paid for: B a divergent
`match` scheme (ADR-0026), C a source of truth that lives in one
checkout (GH-1100 E22).

With Option A, the recommended answers to ADR-0025's four open
questions are these.

1. **Non-suppressible rules.** Extend `SUPPRESSION_REFUSED_KEYS` to
   `base_asks`, and apply the same refusal to `overlay.remove`. A deny
   is already refused. An ask exists because a prompt was judged worth
   paying (GH-604, DX014), so a user `remove:` should not be able to
   silence it either. A user who disagrees can still add an `allow`
   locally. Claude Code evaluates ask before allow, so the ask still
   wins, and the disagreement stays visible.
2. **`local_only` needs a key.** GH-1471 requires that the classifier
   never re-ask about a rule. "What is never promoted" has no memory,
   and a key is the memory. The key is never seeded.
3. **Userspace forks already on disk stay working.** ADR-0021 means they
   no longer shadow. They merge. `user_only` additions keep applying
   globally. `permission doctor` offers to move each one into the
   overlay of the repo it was observed in. The global-scope read is
   registered in the ADR-0028 register as a `config`-audience
   deprecation (six-minor window).
4. **Divergence reporting.** `catalog-diff --strict` stays the detector
   and learns the overlay as a third input. `plugin-doctor` gains one
   thin strategy that calls it per worktree root. That answers GH-1471's
   "doctor" row without a second implementation.

The `merge-worktree` verdict gains three tiers:

- **local-only** writes to `overlay.local_only`.
- **project** writes to `overlay.allow`.
- **global-candidate** produces a proposal a human accepts. It never
  auto-writes, which is the `WRITE_TOOLS_NOT_SEEDED` precedent.

The noise and generalize patterns move from Python literals into
catalog YAML so a project can extend them.

**Step 2 of GH-1313 is decided by disposition class, not by group.**
The 2026-09-18 triage on GH-1313 reduced the backlog to six classes.
This ADR adopts them as the unit of decision:

- **R**, rules the redirect hook already blocks, and **X**, arbitrary
  execution: `RULES_NOT_SEEDED`.
- **W**, external writes: `RULES_NOT_SEEDED`.
- **S**, read-only: seed, except `printenv`/`env`, which go to
  `base_asks`, and the four `${CLAUDE_PLUGIN_ROOT}` rules, which need
  the `update-paths` treatment.
- **D**, state-changing git, and **L**, raw linters and test runners:
  supervisor call.

## Open Questions for the supervisor

1. Accept Option A over B? The deciding trade-off is one file with two
   concerns (A) against two `projects[].match` resolvers (B).
2. Should `base_asks` join `SUPPRESSION_REFUSED_KEYS` (recommendation
   1)? The alternative is to leave asks suppressible by a
   deliberate user `remove:`.
3. Confirm R / X / W as not-seeded, and decide **D** (state-changing
   git) and **L** (raw linters). For L, weigh the friction relief
   against undercutting the `pre-commit` / `run_tests` routing.
4. Should `global-candidate` proposals land as a GitHub issue against
   the plugin, or as a local report the supervisor reviews in
   `Dev10x:upgrade-cleanup`?
5. GH-1471's ledger is empty. Should implementation wait for field
   evidence, or proceed on the design above and let evidence adjust
   it?

## Consequences (if Option A is accepted)

- A permission approved in one worktree is in force in every worktree
  of the repo, including ones created later, because seeding reads the
  overlay.
- `friction.yaml` gains a second concern. A reader looking for gate
  policy will find permission rules beside it.
- `catalog_merge.CatalogDrift` must model the overlay as a third input.
  GH-1100's Goal 3 (seeded-untouched, seeded-then-edited, user-authored)
  becomes implementable rather than aspirational.
- `UNTRIAGED_BACKLOG` falls by whole classes rather than rule by rule,
  and `test_backlog_only_shrinks` keeps each step honest.

## References

- `src/dev10x/skills/permission/catalog_merge.py:52-81, 85-146, 334`
- `src/dev10x/skills/permission/catalog_write.py:696, 995-1053`
- `src/dev10x/skills/permission/merge_worktree_permissions.py:33-84, 219-275`
- `src/dev10x/skills/permission/provenance.py:25-47`
- `src/dev10x/skills/permission/baseline_coverage.py:73-119`
- `src/dev10x/session/preset_pin.py:100, 264`
- `src/dev10x/mcp/gate_query.py:65-104`: the worktree→repo fallback
  the overlay read should share
- [ADR-0021](0021-permission-catalog-merges-rather-than-shadows.md),
  [ADR-0025](0025-projects-yaml-is-the-authoritative-permission-catalog.md),
  [ADR-0026](0026-projects-match-names-its-addressing-scheme.md),
  [ADR-0028](0028-deprecations-carry-a-removal-version.md)
- [GH-1313](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1313),
  [GH-1471](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1471)
