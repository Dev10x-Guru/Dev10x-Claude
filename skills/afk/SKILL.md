---
name: Dev10x:afk
description: >
  Walk-away mode — compose the walk-away gate policy so long-running
  sessions do not stall on re-strategy or confirmation gates. Writes
  gate_preset: adaptive and gate_overlays: [afk] to
  .claude/Dev10x/session.yaml; the resolve_gate resolver reads those
  keys and auto-advances the pipeline while routing deferred decisions
  to the PR description.
  TRIGGER when: starting a long-running unattended session (e.g.,
  bundle work, fanout swarm, overnight implementation), or user says
  "walk away" / "afk" / "headless" / "no more questions".
  DO NOT TRIGGER when: actively pair-programming, scoping a new
  ticket (use Dev10x:ticket-scope), or session is already complete.
user-invocable: true
invocation-name: Dev10x:afk
allowed-tools:
  - Read(.claude/Dev10x/session.yaml)
  - Write(.claude/Dev10x/session.yaml)
---

# Dev10x:afk — Walk-Away Mode

**Announce:** "Using Dev10x:afk to compose the walk-away gate policy for this session."

Sets the session gate policy to the walk-away posture so the agent
does not re-litigate a decision the supervisor already made. It does
this the ADR-0016 way — by **composing a preset with an overlay**, not
by hardcoding modes:

```yaml
gate_preset: adaptive        # walk-away base (merges included, ADR-0016 D-9)
gate_overlays: [afk]         # session_adoption: auto-advance + doubt_sink: pr-description
```

Skills are policy-ignorant: they call the `resolve_gate` tool, which
reads these keys and decides whether each gate fires, auto-advances,
or is skipped. This skill's only job is to write the policy; it never
re-implements gate behavior in prose.

Two effects follow from the composed policy:

1. Gates auto-advance to their `(Recommended)` option unless a safety
   floor fires (secret access, destructive+irreversible, cross-author
   push, privacy disclosure, hard upstream blocker). Those floors are
   the resolver's concern, not this skill's.
2. The `afk` overlay sets `session_adoption: auto-advance` (trust the
   persisted session even when stale) and `doubt_sink: pr-description`,
   so a mid-flight doubt is appended to the PR body instead of pausing.

See [`references/friction-levels.md`](../../references/friction-levels.md)
and [`references/walk-away.md`](../../references/walk-away.md) for the
resolver contract downstream skills consult.

## Orchestration

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Enable walk-away mode", activeForm="Enabling walk-away")`

Mark completed when the session config write returns (or is skipped
because the policy already matches).

## When to Use

Invoke this skill at the start of a session where the supervisor
will be unavailable for hours. Typical entry points:

- `Dev10x:afk` then `Dev10x:work-on bundle <milestone-url>`
- `Dev10x:afk` then `Dev10x:fanout` over a queue of tickets
- Resuming an unattended run after compaction — the policy survives
  in `session.yaml` and is re-read on the next Phase 0

## Instructions

### Step 1: Read existing session config

Read `.claude/Dev10x/session.yaml` if it exists. Capture the
new-style keys `gate_preset`, `gate_overlays`, `gate_overrides` and
the legacy keys `friction_level`, `active_modes`, `walk_away` (present
in sessions written before the afk rewrite). If the file is missing,
treat all keys as unset.

### Step 2: Compute desired state

The walk-away policy composes the `adaptive` base preset with the
`afk` overlay:

```yaml
gate_preset: adaptive
gate_overlays: [afk]
```

Overlay resolution rules:

1. **Compose, do not append modes.** Start from any existing
   `gate_overlays`; add `afk` if absent. Never write
   `active_modes: [solo-maintainer]` — walk-away autonomy and
   solo-maintainer merge autonomy are **orthogonal** overlays
   (`afk` never implies auto-merge; the `adaptive` base already
   decides the merge posture per ADR-0016 D-9).
2. **Reconcile conflicting oversight config.** If the session carries
   structural oversight modes that force checkpoints
   (`supervised`, `pair-review`) in `active_modes` or as overlays,
   drop them — they oppose walk-away and would keep gates firing.
3. **Preserve a pre-existing `solo-maintainer` overlay.** If the
   user already opted into solo-maintainer, keep it in the union
   (`gate_overlays: [afk, solo-maintainer]`); just do not add it.
4. **Migrate legacy keys.** If the file only has the legacy shape
   (`friction_level` / `active_modes` / `walk_away`), replace it with
   the new-style keys above. A pre-existing `walk_away: true` is
   subsumed by the `afk` overlay; a pre-existing `solo-maintainer` in
   `active_modes` becomes the `solo-maintainer` overlay (rule 3).

`doubt_sink` and `session_adoption` come from the `afk` overlay — do
not write them as top-level session keys.

### Step 3: Read-before-write gate (GH-846)

**Skip the write entirely** if `gate_preset` and the resolved
`gate_overlays` set already match the on-disk values. This avoids
spurious permission prompts and prevents clobbering co-edited entries.

Only when the preset or the overlay set differs, write the merged
config back to `.claude/Dev10x/session.yaml` using the Write tool.
When migrating a legacy file, drop the superseded `friction_level` /
`active_modes` / `walk_away` keys in the same write.

### Step 4: Report

Print a one-line summary of what changed:

- `gate_preset: adaptive` — walk-away base selected
- `gate_overlays: + afk` — overlay composed
- `gate_overlays: already [afk]` — no-op, surface as confirmation
- `reconciled: dropped supervised/pair-review` — when structural
  oversight modes were removed
- `migrated: legacy walk_away/active_modes → preset+overlays` — when
  a pre-rewrite file was upgraded

Do **not** emit an `AskUserQuestion` confirmation. The invocation
itself is the confirmation; firing a gate here would violate the
policy this skill is meant to enforce.

## Contract for Downstream Skills

Downstream skills do **not** read `gate_preset` / `gate_overlays`
themselves and they do **not** re-derive gate behavior from
`walk_away`. They call `resolve_gate(gate=..., context=...)` and honor
the returned effect (`ask` / `auto-advance` / `skip`). The resolver
composes this skill's preset + overlays, applies project and per-gate
overrides, then enforces the safety floors.

That means walk-away autonomy is expressed once — here, as policy —
and every gate-emitting skill inherits it uniformly. See
[`references/friction-levels.md`](../../references/friction-levels.md)
for the resolver contract and the per-gate toggle table.

## Relationship to Presets and Overlays

`afk` is an **overlay**, not a friction level. It patches two toggles
on top of whichever base preset the session runs:

| Toggle | `afk` overlay value | Effect |
|--------|---------------------|--------|
| `session_adoption` | `auto-advance` | Adopt the persisted session even when stale — no "is this session still valid?" prompt |
| `doubt_sink` | `pr-description` | Append mid-flight doubts to the PR body instead of pausing |

The base preset decides the rest, including merge:

- `gate_preset: adaptive` (this skill's default) — full walk-away,
  **merges included**.
- `gate_preset: guided` — light-AFK: auto-advance the mechanical
  pipeline through self-review, but **merge stays a human action**
  (`merge: skip`). Compose `afk` onto `guided` when you want
  walk-away autonomy that still stops short of auto-merge.

To keep auto-merge off on a team repo, run with `gate_preset: guided`
+ `gate_overlays: [afk]`; the `adaptive` default is for genuinely
solo / auto-merge-approved contexts.

## Anti-Patterns

- **Calling `Dev10x:afk` mid-flight to silence an active prompt** —
  this skill sets session policy, it does not retroactively cancel a
  pending `AskUserQuestion`. Answer the prompt first, then invoke
  `Dev10x:afk` to change how the next gate resolves.
- **Adding `solo-maintainer` to make afk "more autonomous"** — afk
  and solo-maintainer are orthogonal. If you want auto-merge, that is
  the `adaptive` base or the `solo-maintainer` overlay, chosen
  deliberately — not a side effect of walking away.
- **Using on a session where the supervisor is actively reviewing** —
  walk-away auto-advances informational gates too, removing the
  ability to inject mid-session steering. Reserve for genuinely
  unattended runs.

## Reverting

To exit walk-away mode mid-session, edit `.claude/Dev10x/session.yaml`
and remove `afk` from `gate_overlays` (and reset `gate_preset` to
`guided` or `strict` if desired). The next gate-emitting skill reads
the updated policy via `resolve_gate` and resumes normal behavior.
