# Durable Configuration Schema (v2)

Schema for the durable preferences read by SessionStart hooks and
`resolve_gate`. **Schema v2** is the ADR-0022 shape: one baseline
preset, so there is nothing to select, and one key naming whether the
supervisor reads the PR.

> **ADR-0018 relocation (GH-812).** Durable prefs live in the
> **global `~/.config/Dev10x/friction.yaml`**, keyed by project
> dir-path globs — never in a per-repo `.claude/Dev10x/config.yaml`.
> The ephemeral `.claude/Dev10x/session.yaml` is retired; session
> identity for the adoption gate comes from plan-sync. Nothing durable
> is written under a repo's `.claude/`, so Claude Code's self-settings
> gate never fires on Dev10x state. A legacy per-repo `config.yaml` is
> still *read* as a migration fallback.

## File location

```
~/.config/Dev10x/friction.yaml
```

Machine-global, keyed by project. The resolver reads the first
matching `projects[]` entry, then the legacy per-repo `config.yaml`,
then `defaults:`. Written once when absent by `dev10x session seed`
(or `Skill(Dev10x:session-config-seed)`), hand-authored thereafter.

```yaml
defaults:
  supervisor_review: required     # required | none
  active_modes: []
projects:
  - match: ["*/my-solo-repo", "*/my-solo-repo-*"]
    supervisor_review: none
    gate_overlays: [solo-maintainer]
    gate_overrides: {merge: ask}
    allowed_overlays: []
    tracker: github
```

## Schema definition

Durable keys, in `defaults:` or a `projects[]` entry. Any key outside
this set is dropped by the reader before it reaches the resolver.

| Field | Type | Default | Notes |
|---|---|---|---|
| `supervisor_review` | `required` \| `none` | `required` | ADR-0022 D-2 |
| `active_modes` | list of strings | `[]` | Non-gate consumers only |
| `gate_overlays` | list of strings | `[]` | `solo-maintainer`, `afk` |
| `gate_overrides` | map | `{}` | Per-toggle pins (ADR-0016 D-4) |
| `allowed_overlays` | list of strings | *unset = permissive* | GH-805 guard |
| `protected_branches` | list of globs | script default | `push_safe` (GH-1031) |
| `tracker` | `linear` \| `jira` \| `github` | `linear` | GH-768 |

**v2 carries no `gate_preset` and no `friction_level`.** There is one
shipped baseline, so naming it says nothing; and the ADR-0002
command-redirect dial that shares the `friction_level` name lives in
the plugin's own `command-skill-map.yaml`, not here.

### `supervisor_review` (ADR-0022 D-2)

Must the supervisor read this PR before the next step is allowed? An
enum rather than a boolean, because the two poles are *states of the
project*, not a negation of one another, and because a future third
value has somewhere to go.

| Value | Behaviour |
|---|---|
| `required` (default) | The review gate floors to `ask`. In a solo repo that gate is `merge`; in a team repo it is `request_review`, where the supervisor pass **precedes** the team request rather than replacing it (ADR-0022 D-3). |
| `none` | The floor lifts, and only then do the baseline, overlays, and pins decide the gate. |

Only the exact literal `none` disables the park. Absent,
unrecognised, and malformed values — `"no"`, `false`, and
deliberately also `"None"` — read as `required`, so every typo fails
toward more oversight. Case folding is withheld on purpose: `"None"`
is likelier a stray Python literal than a considered answer.

Read it with `mcp__plugin_Dev10x_cli__supervisor_review_status`
(which also reports `pinned` — whether an entry names the key at all)
and write it with `pin_supervisor_review`. The gate reads the durable
value **unconditionally**: a `supervisor_review` key passed in a
`resolve_gate` context is dropped into `ignored_context_fields`
(GH-1000), so no caller can self-authorise past the supervisor.

**`none` is a precondition for merge autonomy, not a grant.** It is
expressed as a *floor*, and a floor can only ever force `ask` —
clearing it removes one veto and cannot re-admit autonomy some other
layer withheld. The git-tracked `.dev10x/gate-policy.yaml` `merge:
ask` pin and the `allowed_overlays` guard remain independent vetoes.
The `review:cleared` PR label (GH-1008, GH-1163) is the positive
sign-off signal that lifts the floor for the commits under review.

> `human_review` is the deprecated v1 spelling, retained for one
> release as a read alias. `human_review: false` reads as
> `supervisor_review: none`; anything else reads as `required`.

### `active_modes`

Named modes customising **non-gate** behaviour — structural skill
steps, `Dev10x:verify-acc-dod`'s check filter, and playbook step
`modes:` blocks. It has no gate-resolution role; see
`references/active-modes.md` for the catalog and the reasoning.
Nothing derives overlays from it, so an overlay-only entry leaves
those consumers seeing `[]`. Set both keys when a mode must reach
both surfaces. A config still declaring its posture through the v1
keys is refused rather than translated — `legacy_policy_keys()` in
`src/dev10x/domain/gate_policy.py` names the offending keys, and the
migrator's own v1 readers in
`src/dev10x/domain/config_migration.py` convert them.

### `allowed_overlays` (GH-805)

A private allow-list guarding against a stale or incorrect
high-autonomy overlay being honoured where it should not be. The
resolver drops any computed overlay not named here — which only ever
*removes* autonomy, so it can never make a gate less safe.

| Value | Behaviour |
|---|---|
| *unset* | Permissive — every overlay is honoured (back-compat) |
| `[]` | No high-autonomy overlay is honoured — correct for a team repo |
| `[solo-maintainer]` | Only the listed overlays survive |

Separate from the git-tracked `.dev10x/gate-policy.yaml` pin: that is
shared repo policy for specific toggles; this is private and
whole-overlay.

## Migrating v1 → v2

`dev10x config migrate-schema --dry-run` reports the posture change
per entry; `dev10x config migrate-schema` applies it.

Rewrites `gate_preset` / `friction_level` / `human_review` /
`walk_away` into `supervisor_review` + `gate_overlays`, across the
`defaults:` block and every `projects[]` entry. A legacy per-repo
`config.yaml` is *folded into* `friction.yaml` as a new entry keyed by
the repo stem rather than rewritten (ADR-0018 keeps Dev10x out of a
repo's `.claude/` tree); a repo already covered by a `projects[]`
entry is skipped, since that entry already shadows the legacy file.

**The safety direction is one-way: no config resolves to MORE
autonomy after migration than before.**

| v1 input | v2 `supervisor_review` |
|---|---|
| `supervisor_review` already present | coerced (malformed → `required`) |
| `gate_preset` / `friction_level` of `strict` or `guided` | `required` — an explicit request for oversight outranks a stale `human_review: false` in the same entry |
| real boolean `human_review: false` | `none` — the only input producing it |
| anything else (absent, unset, malformed) | `required` |

`active_modes: [solo-maintainer]` and `walk_away: true` materialise as
`gate_overlays` entries, since only the legacy translation seam
produced those overlays before. `active_modes` itself stays — it is a
playbook/DoD axis the migration does not own — while `friction_level`,
`walk_away`, and `human_review` are dropped, and a retired preset name
(`strict`, `guided`, `adaptive`) is removed rather than rewritten. A
user-defined preset name is a real selection, preserved verbatim.
`.dev10x/gate-policy.yaml` is deliberately not walked: its
`overrides:` are per-toggle pins, still valid verbatim under v2.

Idempotent — an entry already carrying `supervisor_review` and none of
the retired keys is left byte-identical, so a second run writes
nothing.

## Fallback behaviour

Readers degrade softly; no missing or malformed field raises.

- **Missing file, unreadable file, or malformed YAML** — all defaults
  apply, and the SessionStart hook still runs.
- **Missing `supervisor_review`** — `required`.
- **Malformed `active_modes`** (not a list) — `[]`.
- **Malformed `allowed_overlays`** (not a list) — treated as *unset*.
  The distinction between unset and explicitly empty is load-bearing,
  so `[]` survives coercion.

## Readers

`FrictionYamlDocument`
(`src/dev10x/domain/documents/session_yaml.py`) owns the read —
`read_supervisor_review()`, `read_active_modes()`, and the `matched()`
first-match-wins lookup. Policy rules in
`src/dev10x/domain/session_rules.py` consume the parsed values and
perform no I/O (ADR-0007 D3). `resolve_gate` is the only sanctioned
gate consumer; `supervisor_review_status` / `pin_supervisor_review`
are the read and write halves exposed to skills; SessionStart display
rules print the resolved posture and drive no behaviour.

## Testing

- `tests/domain/documents/test_session_yaml.py` — reads and fallbacks
- `tests/domain/test_config_migration.py` — the v1 → v2 mapping table,
  the one-way safety direction, and idempotency
- `tests/session/test_supervisor_review_pin.py` — the pin writer and
  its loud rejection of an unrecognised value

## Related

- `references/friction-levels.md` — how a gate resolves
- `references/active-modes.md` — the non-gate `active_modes` consumers
- `src/dev10x/domain/gate_policy.py` — `coerce_supervisor_review()`,
  `SHIPPED_PRESETS`, `_floors()`
- `src/dev10x/domain/config_migration.py` — the v1 → v2 migrator
