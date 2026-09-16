# ADR-0025: `projects.yaml` is the authoritative permission catalog

- **Status:** Accepted
- **Date:** 2026-09-16
- **Supersedes:** none
- **Amends:** ADR-0021 (names which catalog its merge model applies to)
- **Related:** GH-1313, GH-1100 (sequencing step 4), GH-1090, GH-1215,
  GH-1153, GH-587, GH-1249

## Context

Two rule catalogs of comparable size have coexisted since GH-99, with
different schemas, different consumers, and no relationship between
them that any code enforces.

| | Path | Shape | Read by |
|---|---|---|---|
| **A** | `skills/upgrade-cleanup/projects.yaml` | flat lists (`base_permissions`, `base_denies`, `base_asks`, plus per-tracker and per-IDE blocks) | `ensure_base`, `seed_worktree` |
| **B** | `src/dev10x/skills/permission/baseline-permissions.yaml` | `groups:` keyed by name, each tier-tagged; plus `deprecations:` and `invariants:` | `permission doctor`, `cli_catalog`, `policy_migration`, `enable-group` |

Only **A** is on the write path. `migrate_flat_config` reads exactly
three keys from it — `base_permissions`, `base_denies`, `base_asks` —
projects them into `Policy` objects, and `render_permissions` turns
those into the `allow`/`deny`/`ask` lists a settings file carries.
**B**'s `groups:` block reaches a settings file only when a user runs
`permission doctor --enable-group=<name>` for that group by name.

So a rule can be written into B, cited by a skill's documentation,
relied upon by a hook's steer, and still prompt on every single call,
in every project, forever — while looking fully catalogued everywhere
a reader would think to check. GH-1100 records this twice: **E18**, a
`cp` rule covering the one path a hard-deny excepts, and **E19**, a
`git nopager` rule the plugin steers agents toward in three separate
places. Both existed only in B.

This is the same failure shape as GH-1153, where a registered MCP tool
absent from the catalog prompted forever, and the same shape as
GH-1249, where a userspace fork silently lost whole sections. In each
case the system had the information needed to notice and no mechanism
that compared the two halves.

`last_audited: 2026-05-15` in B was four months stale when GH-1313 was
filed.

## Decision

### 1. `projects.yaml` is authoritative

The authoritative catalog is the one on the **write path**. A rule's
entire value is that it reaches a settings file, and the catalog
nobody seeds from is precisely the one that produced E18 and E19.

`baseline-permissions.yaml` is demoted to migration metadata. It keeps
`deprecations:` and `invariants:` — a genuinely different concern from
rule-bearing, consumed by `permission doctor` to rewrite and warn — and
its `groups:` block is to migrate into `projects.yaml` carrying tier
tags.

**Rejected: generate `projects.yaml` from `baseline-permissions.yaml`.**
B's grouped, tier-tagged model is the cleaner end state on paper, and it
is what the PAP/PDP/PEP target architecture assumes. But a *generated*
seeding catalog means a stale build artifact can silently under-seed —
the same failure as the stale userspace fork, reintroduced one layer
down, and now in front of the write path rather than beside it.

### 2. A rule that cannot be seeded fails a test

`dev10x.skills.permission.baseline_coverage` compares the two catalogs,
and `tests/skills/permission/test_catalog_covers_baseline.py` asserts
the comparison is empty. Every grouped rule must be seeded, or excused
by name.

Three properties make this a guard rather than a gesture:

**The seeded side is derived, not restated.** It is built by folding
every tracker and IDE block into the config and handing the result to
`migrate_flat_config` — the same projection `ensure_base` uses. A
section this module forgot to read therefore cannot masquerade as a
rule the catalog never had. `rule_bearing_sections` separately asserts
that no `*_permissions` / `*_denies` / `*_asks` section exists that the
fold does not know about.

**Exclusion is by name, never by predicate.** Tier-3 groups are opt-in
by design, so their rules are legitimately absent — but they are
excused by naming the fourteen groups, not by testing `tier == 3`.
Re-tagging a seeded group as tier 3 then fails loudly instead of
quietly leaving the guard's field of view. This is the
`WRITE_TOOLS_NOT_SEEDED` precedent from GH-1153: an explicit list makes
an omission a conscious edit, where a heuristic absorbs the next one
silently.

**The enumeration is itself measured.** GH-1215 is the reason. That
ticket records `test_catalog_covers_mcp_tools`'s own discovery narrowed
to five of twelve modules, passing 3/3 while blind to four fifths of
its surface — a healthy-looking green over a guard that had stopped
guarding. So `test_enumeration_finds_every_declared_rule` counts rule
lines in the raw YAML text and asserts the parser found at least that
many. A guard only ever sees what its enumeration sees, and an
enumeration nothing checks is a guard nothing checks.

### 3. The pre-existing divergence is a ratchet, not an exemption

The guard found **189** rules across 17 tier-1/tier-2 groups that no
seeding path can deliver. E18 and E19 were not two incidents; they were
two of 189.

Those 189 are recorded in `UNTRIAGED_BACKLOG`. It may shrink and must
never grow — `test_backlog_only_shrinks` refuses growth, and
`test_backlog_carries_no_resolved_entries` reports entries that no
longer need a decision, so the remaining debt stays countable.

They are recorded rather than seeded because seeding them is a
**security decision, not a mechanical one**. The set includes rules
granting arbitrary code execution (`npx:*`, `pip install:*`,
`docker exec:*`, `python3:*`), raw database access the `Dev10x:db`
skill exists to route around (`psql:*`), tracker writes, and raw `gh`
spellings the skill-redirect hook deliberately steers to MCP wrappers
(`gh pr merge`, `gh issue close`). Shipping those wholesale would widen
every Dev10x user's default permission surface — the opposite of what
GH-1313 is for, and not a change that should land as a side effect of
adding a test.

The value of the ratchet is that it is available immediately: new
divergence fails today, while the backlog is triaged at whatever pace
a supervisor can review it.

### 4. The user overlay is a delta, not a fork

User customisation lives as a `permissions:` block (`allow` / `remove`
/ `deny`) in the matching `projects[]` entry of
`~/.config/Dev10x/friction.yaml`, reusing `pin_project_prefs` and
`resolve_repo_identity`. Repo identity comes from the git **common
dir**, which every worktree of a repo shares by construction, so one
answer covers the repo and every worktree — past and future.

This settles which base ADR-0021's merge model applies over. Its
`⊕ user_additions ⊖ user_suppressions` semantics are unchanged; what
changes is that the base is now named, and the overlay is a delta, so
a plugin upgrade delivers new shipped rules to a customised install
with no manual merge. A full-copy fork absorbs none of that — the
catalog grew 348 → 419 rules across one minor release.

## Consequences

**Positive.** The E18/E19 class cannot recur: a rule added to the
grouped catalog and not seeded fails CI. The cost of the divergence is
now a number (189) rather than an anecdote, which is what makes it
schedulable. `migrate_flat_config` is confirmed as the single
projection both the seeding path and the guard read through.

**Negative.** Two catalogs still exist, and the guard's green is
qualified by a 189-rule exclusion. That is honest debt, not hidden
debt, but a reader who sees only the passing test will overstate what
is covered — hence this section.

**Deferred — migrating `groups:` into `projects.yaml`.** Decision 1 is
made; the migration is not done. It needs tier tags in `projects.yaml`,
which is a schema change to the authoritative catalog, and it needs the
189-rule triage above. The guard makes that migration safe to do
incrementally: a partially-migrated state fails loudly instead of
under-seeding quietly.

**Not addressed.** The four questions GH-1313 leaves open are
deliberately untouched: whether any shipped rule is non-suppressible by
a user `remove:`; whether `local_only` needs a key or is simply what is
never promoted; whether userspace forks already on disk are converted
or deprecated over a release; and whether `plugin-doctor` gains a
divergence strategy or that stays with `catalog-diff --strict`.

## Alternatives considered

**Seed all 189 rules and land a fully green guard.** Rejected above:
it changes every user's default permission surface, and the review that
change deserves is not the review a test PR gets.

**Populate `RULES_NOT_SEEDED` with all 189 and reasons.** Rejected:
"deliberately withheld" would be false for most of them. A rule nobody
has triaged and a rule someone decided to withhold must not look alike
to the next reader — that indistinguishability is the defect this whole
issue is about.

**Skip the guard, do the migration first.** Rejected: the migration is
exactly when under-seeding is easiest to introduce and hardest to see.
The guard is what makes the migration safe, so it goes first — which is
also the ordering the supervisor set on GH-1313.
