---
name: Dev10x:spec-update
invocation-name: Dev10x:spec-update
description: >
  Enforce SPDD's "fix the prompt first" Golden Rule for logic
  changes. When the user wants to change behaviour (not refactor),
  walk them through editing the canonical spec at
  docs/specs/<TICKET-ID>.md FIRST, then re-invoke
  Dev10x:work-on to regenerate code from the updated spec. Refuses
  to proceed if the user tries to edit code directly without a
  spec update.
  TRIGGER when: requirements shift mid-implementation and the
  canonical spec exists; user describes a behaviour change for a
  ticket that already has docs/specs/<TICKET-ID>.md.
  DO NOT TRIGGER when: refactor without behavior change (use
  Dev10x:spec-sync instead); ticket has no canonical spec (regular
  Dev10x:work-on applies); user is creating a new spec for the
  first time (use Dev10x:ticket-scope).
user-invocable: true
allowed-tools:
  - AskUserQuestion
  - Read
  - Edit
  - Write
  - Bash(git diff:*)
  - Bash(git status:*)
  - Skill
  - TaskCreate
  - TaskUpdate
  - TaskList
---

# Dev10x:spec-update — Spec-First Behaviour Change

## Overview

Implements SPDD's [Golden Rule](https://github.com/Dev10x-Guru/Dev10x-Claude/blob/main/docs/adr/0005-spdd-pipeline.md):
**when behaviour must change, fix the prompt first, then regenerate
the code.** The spec at `docs/specs/<TICKET-ID>.md` is the source
of truth — drifting code away from it silently corrupts future
generation passes.

This skill refuses to proceed if the user tries to edit code
directly without first updating the spec.

## Orchestration

**REQUIRED: Create task at invocation.**

1. `TaskCreate(subject="Update spec before regenerating code",
   activeForm="Walking through spec edit")`

Mark completed after Step 5 (re-invoke `Dev10x:work-on`) succeeds.

## Interface Contract

```
INPUTS:
  ticket_id: str           — e.g. GH-171, FEAT-300
  change_description: str  — what behaviour must change
  spec_path: Path | None   — defaults to docs/specs/<TICKET-ID>.md

OUTPUTS:
  regenerated: bool — true if Dev10x:work-on ran successfully

SIDE EFFECTS:
  - Modifies docs/specs/<TICKET-ID>.md
  - Invokes Dev10x:work-on which may modify source files
```

## Workflow

### Step 1: Locate the Canonical Spec

Resolve `spec_path` from `ticket_id` if not supplied:
`docs/specs/<TICKET-ID>.md`.

If the file does not exist, **STOP**. Surface to the user:

> "No canonical spec found at `docs/specs/<TICKET-ID>.md`. This
> skill enforces spec-first behaviour changes — a missing spec
> means there is no source of truth to update. Run
> `Dev10x:ticket-scope` first to create one, then re-invoke
> this skill."

### Step 2: Classify the Change

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
Classify the change so the right path runs:

- **Behaviour change (Recommended)** — Requirements / Acceptance
  Criteria / Job Story / Safeguards change. This skill applies.
- **Structural refactor** — Code shape changes, behaviour stable.
  This skill bails out and delegates to `Dev10x:spec-sync`.
- **New feature, no spec yet** — There is no spec to update. This
  skill bails out and delegates to `Dev10x:ticket-scope`.

If anything other than "Behaviour change" is selected, route to
the named skill via `Skill(...)` and exit.

### Step 3: Read the Current Spec

`Read` the spec file. Surface to the user the sections most likely
to need updates: Job Story, Requirements / Acceptance Criteria,
Norms, Safeguards. The `## Implementation Steps` section is NOT
the source of truth — it is downstream of the others.

### Step 4: Walk the User Through the Spec Edit

For each section identified in Step 3:

1. Show the current content
2. Ask what should change (free-form text or AskUserQuestion as
   appropriate)
3. Apply the edit with the `Edit` tool

**Anti-pattern guard.** If the user tries to skip ahead and
modify source code, **STOP**. Refuse with:

> "Spec must be updated before code. The Golden Rule says: fix
> the prompt, then regenerate. Editing code first creates drift
> that the next generation pass will silently revert."

### Step 5: Re-invoke `Dev10x:work-on`

After the spec is saved:

```
Skill(skill="Dev10x:work-on", args="<ticket_id>")
```

`work-on` will pick up the updated spec and regenerate code from
the new requirements. The structured-spec play (GH-174, when
landed) routes through this skill automatically.

### Step 6: Verify Code Matches Spec

After regeneration, run `Dev10x:spec-sync` in **check-only mode**
to confirm no structural drift remains:

```
Skill(skill="Dev10x:spec-sync", args="--check-only <ticket_id>")
```

If drift remains, surface it to the user. The session terminates
with the supervisor's confirmation that the code now matches the
updated spec.

## Decision Gates

This skill has **two REQUIRED `AskUserQuestion` gates**:

1. **Step 2 — Change classification.** Routes between this skill,
   `Dev10x:spec-sync`, and `Dev10x:ticket-scope`. Plain-text
   substitution would silently default to "behaviour change" and
   break the contract.
2. **Step 4 — Per-section edit approval.** Whenever the proposed
   edit is non-trivial, confirm before writing.

See `.claude/rules/skill-gates.md` for the pattern.

## Integration Points

- **`Dev10x:ticket-scope`** — creates the canonical spec this
  skill updates.
- **`Dev10x:spec-sync`** — the inverse path (refactor-only).
  Shares the `drift_detector` module (GH-172).
- **`Dev10x:work-on`** — invoked at Step 5 to regenerate code
  from the updated spec.
- **`Dev10x:gh-pr-respond`** — runs drift check before applying
  fixups (GH-173). If drift is found, the user is prompted to
  invoke this skill.
- **`Dev10x:git-groom`** — pre-merge drift check (GH-173) blocks
  the merge if a behaviour change shipped without a spec update.

## Anti-Patterns

- ❌ Editing the spec **after** the code change (drift created,
  not fixed).
- ❌ Skipping Step 5 — without re-invoking `Dev10x:work-on`, the
  code does not yet reflect the new spec.
- ❌ Editing only Implementation Steps without touching Job
  Story / Acceptance Criteria / Safeguards. Implementation Steps
  are downstream of those sections; they are not the source of
  truth.

## References

- ADR 0005 — SPDD pipeline rationale
- `references/skill-pipelines.md` — Structured Spec Pipeline
  section (added by GH-175)
- `.claude/rules/skill-gates.md` — decision gate pattern
