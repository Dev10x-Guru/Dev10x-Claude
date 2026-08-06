# ADR-0021: The permission catalog merges rather than shadows

- **Status:** Accepted
- **Date:** 2026-08-06
- **Supersedes:** none
- **Related:** GH-912, GH-925 (A3), GH-796, ADR-0018

## Context

Dev10x stores permission truth in three tiers:

| Tier | Path | Owner |
|---|---|---|
| Plugin catalog | `skills/upgrade-cleanup/projects.yaml` | plugin (shipped defaults) |
| Userspace catalog | `~/.config/Dev10x/projects.yaml` | user |
| Effective settings | `<repo>/.claude/settings.local.json` | Claude Code engine |

PERM-M5 (GH-797–GH-802, PR #814) and its wiring follow-up (GH-819,
PR #870) introduced a `Policy` domain object whose `source` field
already names these tiers — `PLUGIN_DEFAULT`, `USER_PRIVATE`,
`PROJECT_LOCAL` — and `resolve_effect` implements
*project-local > user-private > plugin-default* with forbid-wins.
`load_policy_layers` accepts three separate catalog paths and merges
them into one tagged policy set.

That merge is not on the read path. `resolve_config`
(`skills/permission/config.py`) returns the **first existing**
candidate:

```python
for candidate in candidates:
    if candidate.is_file():
        return ok(candidate)          # returns ONE path
```

Every `permission` subcommand loads its catalog through
`build_context()`, which calls `find_config()` → `resolve_config` →
a single winner. Because `~/.config/Dev10x/projects.yaml` is created
once by `permission init` and then sits first in the candidate list,
**it shadows the shipped catalog permanently**. Every safe default
shipped after that first init is invisible, and `ensure-base`
validates project settings against the frozen copy and reports
success.

Measured on one install (GH-925 F1): 320 shipped entries vs 323
userspace, with 5 shipped entries missing from the userspace copy and
8 userspace-only entries — of which 5 are ADR-0018/GH-941 relics and
3 are genuine user preference. Nothing in the system can tell those
two groups apart, and `permission clean` reports the file healthy.

The observable cost is one permission prompt per tool per project,
answered by hand, indefinitely.

## Decision

**The catalog read path merges all available tiers instead of
selecting one.** Effective catalog content is:

```
effective = shipped_default
          ⊕ user_additions       (user entries absent from shipped)
          ⊖ user_suppressions    (explicit, opt-in opt-outs)
```

Four rules make this concrete.

### 1. Shipped defaults always flow through

A new entry in the plugin catalog reaches every install on the next
run, with no re-init and no migration. This is the property the
first-wins model destroyed and the reason the drift went unnoticed
for months.

### 2. Suppression is explicit and cannot drop a deny

Removing a shipped allow rule requires naming it under a new
`base_permission_suppressions:` key. Absent that key — the state of
every existing install — behaviour is purely additive, so the change
is backward compatible by construction.

Suppressions apply to `base_permissions` only. **A user suppression
may not drop a shipped `base_denies` entry.** Denies are the safety
floor, and GH-925 E6 records a case where a destructive-op prompt was
correct and the agent's justification for bypassing it was false. The
destructive axis stays untouchable, matching `resolve_effect`'s
forbid-wins precedence.

### 3. Non-permission keys stay user-owned

`roots`, `workspace_directories`, `include_user_settings` and similar
describe *this user's machine*, not shared policy. They are read from
the userspace catalog alone; the shipped catalog does not contribute
or override. Only `base_permissions` and `base_denies` merge.

### 4. Drift is reported, never silent

`dev10x permission catalog-diff` reports the three-way split —
shipped-but-missing, user-only, suppressed — and exits non-zero when
the userspace copy is missing at least one shipped entry. Silence was
the actual defect: `ensure-base` succeeded against a stale catalog,
so the only signal a user ever got was a prompt at point of use.

## Consequences

**Positive.** New shipped defaults propagate without user action.
Genuine user preference survives a re-seed, because merging never
rewrites the userspace file. The `user-only` column produced by
`catalog-diff` is the classification fixture GH-925 A3 asked for:
entries appearing there are either preference or relic, and a human
decides which — but now with a report rather than an archaeology
session.

**Negative.** A user who deliberately deleted a shipped rule from
their userspace copy will see it return, and must re-express the
removal as a suppression. This is the correct trade — silent deletion
is indistinguishable from drift, which is the problem being fixed —
but it is a real behaviour change and `catalog-diff` names the
affected entries so the migration is mechanical.

**Deferred.** This ADR does not give the `user-private` tier its own
file. `Policy.source.USER_PRIVATE` remains modelled-but-unhoused, and
users still express preference by editing the same
`~/.config/Dev10x/projects.yaml` the plugin seeds. A dedicated
`permission-preferences.yaml` overlay (GH-925 A3.3) is the natural
next step and is what finally removes the reason to edit the seeded
catalog at all. Merging first is what makes that overlay safe to add:
the merge semantics are settled and tested before a fourth file
exists.

**Not addressed.** Whether a `Bash(...)` rule with a mid-path `*`
can match at all (GH-925 F2) is an empirical question gating any
catalog *rewrite*. This ADR changes how catalogs are combined, not
what shapes they contain, so it is independent of that matrix.

## Alternatives considered

**Keep first-wins, teach `ensure-base` to warn.** Rejected: it leaves
the stale copy authoritative and turns a correctness bug into a
notification the user must act on manually, per project, forever.

**Re-seed the userspace catalog from shipped on every run.** Rejected:
it destroys user customisation, which is precisely what GH-912's Job
Story asks to preserve across a re-seed.

**Merge at `render_permissions` instead of at load.** Rejected: the
renderer is downstream of `migrate_flat_config` and would have to
re-derive tier provenance the loader already knows. `load_policy_layers`
exists at the right level; the fix is to route the read path onto it.
