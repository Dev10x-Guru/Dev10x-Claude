---
name: Dev10x:afk
description: >
  Walk-away mode — compose the walk-away gate policy so long-running
  sessions do not stall on re-strategy or confirmation gates. Writes
  gate_preset: adaptive and gate_overlays: [afk] to the global
  ~/.config/Dev10x/friction.yaml via `dev10x session set-friction`
  (ADR-0018); the resolve_gate resolver reads those keys and
  auto-advances the pipeline while routing deferred decisions to the PR
  description.
  TRIGGER when: starting a long-running unattended session (e.g.,
  bundle work, fanout swarm, overnight implementation), or user says
  "walk away" / "afk" / "headless" / "no more questions".
  DO NOT TRIGGER when: actively pair-programming, scoping a new
  ticket (use Dev10x:ticket-scope), or session is already complete.
user-invocable: true
invocation-name: Dev10x:afk
allowed-tools:
  - mcp__plugin_Dev10x_cli__preset_pin_status
  - Bash(uvx dev10x session set-friction:*)
  - Bash(dev10x session set-friction:*)
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

**Where the policy lives (ADR-0018).** The only home for gate prefs is
the global `~/.config/Dev10x/friction.yaml`, written through
`dev10x session set-friction`, which locks + atomically writes
(GH-827 / ADR-0011). This skill never uses `Write`/`Edit` on any path —
and in particular never under the repo's `.claude/` tree, so Claude
Code's self-settings consent gate never fires (GH-812). The per-repo
`.claude/Dev10x/config.yaml` and the ephemeral
`.claude/Dev10x/session.yaml` are **retired**; a checkout that still
carries one is folded into `friction.yaml` by
`dev10x permission migrate-config` (GH-818), not by this skill.

**The write is durable, not per-session.** Since ADR-0018 deleted the
ephemeral session store, walk-away posture persists for this checkout
until it is changed — a later session in the same directory starts
already in walk-away. That is deliberate (an unattended run survives
compaction and restarts), so read [Reverting](#reverting) before
invoking on a repo you also pair-program in.

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

Mark completed when the `set-friction` write returns (or is skipped
because the policy already matches).

## When to Use

Invoke this skill at the start of a session where the supervisor
will be unavailable for hours. Typical entry points:

- `Dev10x:afk` then `Dev10x:work-on bundle <milestone-url>`
- `Dev10x:afk` then `Dev10x:fanout` over a queue of tickets
- Resuming an unattended run after compaction — the policy survives
  in `friction.yaml` and is re-read on the next Phase 0

## Instructions

### Step 1: Read the existing policy

Call `mcp__plugin_Dev10x_cli__preset_pin_status` — it reads this
checkout's `projects[]` entry out of the global
`~/.config/Dev10x/friction.yaml` and returns:

- `pinned` — `false` when no entry covers this checkout (treat every key
  as unset)
- `prefs` — the current `gate_preset`, `gate_overlays`, `gate_overrides`

Do **not** read any file under the repo's `.claude/` tree for policy.
There is nothing durable there to read (ADR-0018), and a legacy
`config.yaml` left behind by an old install is migrated by
`dev10x permission migrate-config`, not by this skill.

### Step 2: Compute desired state

The walk-away policy composes the `adaptive` base preset with the
`afk` overlay:

```yaml
gate_preset: adaptive
gate_overlays: [afk]
```

Overlay resolution rules:

1. **Compose, do not append modes.** Start from the `gate_overlays` in
   `prefs`; add `afk` if absent. Walk-away autonomy and solo-maintainer
   merge autonomy are **orthogonal** overlays (`afk` never implies
   auto-merge; the `adaptive` base already decides the merge posture per
   ADR-0016 D-9).
2. **Reconcile conflicting oversight overlays.** If `prefs` carries
   structural oversight overlays that force checkpoints
   (`supervised`, `pair-review`), drop them — they oppose walk-away and
   would keep gates firing.
3. **Preserve a pre-existing `solo-maintainer` overlay.** If the
   user already opted into solo-maintainer, keep it in the union
   (`gate_overlays: [afk, solo-maintainer]`); just do not add it.
4. **Carry forward the existing `gate_overrides` verbatim.**
   `set-friction` *replaces* this checkout's entry rather than merging
   into it, so every override already in `prefs` must be re-passed in
   Step 3 or it is silently dropped. This skill changes the preset and
   the overlay set only; it never invents or removes a per-gate
   override.

`doubt_sink` and `session_adoption` come from the `afk` overlay — do
not write them as top-level keys.

### Step 3: Read-before-write gate (GH-846)

**Skip the write entirely** if the `gate_preset` and the resolved
`gate_overlays` set from Step 2 already match the `prefs` returned in
Step 1. This avoids a redundant subprocess and keeps a re-invocation a
visible no-op.

Only when the preset or the overlay set differs, persist the composed
policy with **one** command — never with `Write`/`Edit`:

```bash
uvx dev10x session set-friction --preset adaptive --overlay afk
```

- Repeat `--overlay <name>` once per overlay in the resolved set (e.g.
  `--overlay afk --overlay solo-maintainer`).
- Repeat `--gate-override <toggle>=<value>` once per override carried
  forward from Step 2 rule 4.
- The entry is keyed off this checkout's path, so a run inside a
  worktree configures that worktree. Use `Dev10x:friction-setup`
  (`dev10x session pin`) instead when the supervisor wants a posture
  that spans the repo and every future worktree of it (GH-855).
- The command is idempotent — a re-run replaces this checkout's entry
  rather than appending a second one.

### Step 4: Report

Print a one-line summary of what changed:

- `gate_preset: adaptive` — walk-away base selected
- `gate_overlays: + afk` — overlay composed
- `gate_overlays: already [afk]` — no-op, surface as confirmation
- `reconciled: dropped supervised/pair-review` — when structural
  oversight overlays were removed
- `preserved: gate_overrides <toggle>=<value>, …` — when overrides were
  carried forward through the replace

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

**Self-initiated gates still need the `ALWAYS_ASK` check.** When the
composed policy resolves to auto-advance, a downstream skill must not
open a self-initiated `AskUserQuestion` just because a decision feels
uncertain. Check it against the `ALWAYS_ASK` allowlist first — secret
access, destructive+irreversible actions, cross-author force-push. If
the decision is not on that allowlist, decide-and-log instead of
asking; asking anyway freezes the run exactly like the anti-pattern
below.

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

To exit walk-away mode, re-run `set-friction` **without** `--overlay
afk` — re-passing every other overlay and override you want to keep,
since the write replaces the entry:

```bash
uvx dev10x session set-friction --preset guided
```

The next gate-emitting skill reads the updated policy via `resolve_gate`
and resumes normal behavior. Do **not** hand-edit `friction.yaml` (or
anything under the repo's `.claude/`) to revert — the CLI holds the lock
that keeps parallel worktrees from clobbering each other (GH-827).
