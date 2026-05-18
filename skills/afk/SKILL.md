---
name: Dev10x:afk
description: >
  Walk-away mode — harden adaptive + solo-maintainer auto-advance so
  long-running sessions do not stall on re-strategy or confirmation
  gates. Writes walk_away: true and doubt_sink: pr-description to
  .claude/Dev10x/session.yaml; downstream skills consult the flag and
  route mid-flight doubts to the PR body instead of pausing.
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

**Announce:** "Using Dev10x:afk to harden auto-advance for this session."

Hardens `friction_level: adaptive` + `active_modes: [solo-maintainer]`
so the agent does not re-litigate a decision the supervisor already
made. Couples two rules:

1. Do not call `AskUserQuestion` unless the action is **destructive**
   (force-push to protected branch, mass delete, secret retrieval) or
   a **hard upstream blocker** (missing ADR, conflicting upstream,
   no auth credentials).
2. If you start to doubt the chosen plan mid-execution, **push through
   and append the doubt to the PR description** under a "Concerns
   surfaced during implementation" header. Do not pause.

See [`references/walk-away.md`](../../references/walk-away.md) for
the full contract downstream skills consult.

## Orchestration

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Enable walk-away mode", activeForm="Enabling walk-away")`

Mark completed when the session config write returns (or is skipped
because the flag already matches).

## When to Use

Invoke this skill at the start of a session where the supervisor
will be unavailable for hours. Typical entry points:

- `Dev10x:afk` then `Dev10x:work-on bundle <milestone-url>`
- `Dev10x:afk` then `Dev10x:fanout` over a queue of tickets
- Resuming an unattended run after compaction — the flag survives
  in `session.yaml` and is re-read on the next Phase 0

## Instructions

### Step 1: Read existing session config

Read `.claude/Dev10x/session.yaml` if it exists. Capture
`friction_level`, `active_modes`, `walk_away`, and `doubt_sink`.
If the file is missing, treat all four as unset.

### Step 2: Compute desired state

The walk-away invariants:

```yaml
friction_level: adaptive            # required
active_modes: [solo-maintainer]     # required (merged, not replaced)
walk_away: true
doubt_sink: pr-description
```

Merge `solo-maintainer` into the existing `active_modes` list if
absent. **Never overwrite a non-empty `active_modes` list with the
single-mode form** — preserve modes the user already enabled (e.g.,
`research-spike`, `release-train`). The merged list is the union.

If `friction_level` is currently `strict` or `guided`, walk-away
**downgrades it to `adaptive`** — that is the entire point. Surface
this to the user in the announcement so they can revert if it was
unintentional.

### Step 3: Read-before-write gate (GH-846)

**Skip the write entirely** if all four desired keys already match
the on-disk values. This avoids spurious permission prompts and
prevents clobbering co-edited entries.

Only when at least one key differs, write the merged config back
to `.claude/Dev10x/session.yaml` using the Write tool.

### Step 4: Report

Print a one-line summary of what changed:

- `walk_away: true` — first time enabling
- `walk_away: already true` — no-op, surface as confirmation
- `friction_level: guided → adaptive` — when downgraded
- `active_modes: + solo-maintainer` — when merged

Do **not** emit an `AskUserQuestion` confirmation. The invocation
itself is the confirmation; firing a gate here would violate the
contract this skill is meant to enforce.

## Contract for Downstream Skills

Skills that emit `AskUserQuestion` MUST consult `walk_away` before
firing. The classification rule:

| Question class | Walk-away behavior |
|----------------|---------------------|
| `destructive` (force-push, mass delete, secret retrieval) | Fire normally (ALWAYS_ASK) |
| `blocking` (missing creds, conflicting upstream, missing ADR) | Fire normally |
| `strategy` / `confirmation` / `re-strategy` | Suppress, auto-pick Recommended, log to `doubt_sink` |
| `informational` (which slug? which title?) | Suppress, pick best-guess, log to `doubt_sink` |

Full classification rules and per-skill integration guidance live in
[`references/walk-away.md`](../../references/walk-away.md).

## Relationship to Friction Levels

`walk_away` is **orthogonal to** `friction_level`. The adaptive
friction level already auto-selects `(Recommended)` options at
gates, but it has two known failure modes that walk-away closes:

1. **Gates without a Recommended option** — adaptive still fires
   them. Walk-away suppresses anything that is not destructive or
   hard-blocking.
2. **Mid-flight re-strategy prompts** — adaptive does not prevent
   a skill from emitting a fresh `AskUserQuestion` after partial
   recon reveals scope. Walk-away forces the doubt into the
   `doubt_sink` instead.

See `references/friction-levels.md` § Walk-Away Layer for the
precedence rules.

## Anti-Patterns

- **Calling `Dev10x:afk` mid-flight to silence an active prompt** —
  this skill modifies session config, it does not retroactively
  cancel a pending `AskUserQuestion`. Answer the prompt first, then
  invoke `Dev10x:afk` to prevent the next one.
- **Combining with `friction_level: strict`** — the skill downgrades
  strict to adaptive. If you want strict gating, do not invoke
  walk-away.
- **Using on a session where the supervisor is actively reviewing** —
  walk-away suppresses informational gates too, which removes the
  ability for the supervisor to inject mid-session steering. Reserve
  for genuinely unattended runs.

## Reverting

To exit walk-away mode mid-session, edit `.claude/Dev10x/session.yaml`
directly and set `walk_away: false` (or delete the key). The
next gate-emitting skill will read the updated value and resume
normal adaptive behavior.
