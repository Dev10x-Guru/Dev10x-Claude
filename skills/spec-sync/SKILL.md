---
name: Dev10x:spec-sync
invocation-name: Dev10x:spec-sync
description: >
  Inverse Golden Rule path: when code is refactored without
  behaviour changes, update the canonical spec at
  docs/specs/<TICKET-ID>.md to match the new code shape.
  Regenerates Architecture / Implementation Steps / Code
  References sections, leaves Requirements / Entities / Norms /
  Safeguards untouched. Bails to Dev10x:spec-update if it detects
  behavioural drift.
  TRIGGER when: a structural refactor (rename, file move, signature
  change) ships and the canonical spec must be re-aligned with the
  new code shape.
  DO NOT TRIGGER when: behaviour changes (use Dev10x:spec-update);
  spec is missing (use Dev10x:ticket-scope); no canonical spec
  workflow is in use (regular Dev10x:work-on applies).
user-invocable: true
allowed-tools:
  - AskUserQuestion
  - Read
  - Edit
  - Write
  - Bash(git diff:*)
  - Bash(git status:*)
  - Bash(dev10x spec drift:*)
  - Bash(uvx dev10x spec drift:*)
  - Skill
  - TaskCreate
  - TaskUpdate
  - TaskList
---

# Dev10x:spec-sync — Refactor-Driven Spec Update

## Overview

When a refactor ships, the spec's Structure / Implementation
Steps / Code References sections describe the **pre-refactor**
shape — that's drift, even though no behaviour changed. This
skill detects structural drift and regenerates those sections.

If behavioural drift is detected, it **refuses to proceed** and
delegates to `Dev10x:spec-update` (the spec-first path). Per
ADR 0005, the shared `drift_detector` module (one canonical
detector, two entry points) ensures both skills agree on what
counts as drift.

## Orchestration

**REQUIRED: Create task at invocation.**

1. `TaskCreate(subject="Sync spec with refactored code",
   activeForm="Syncing spec to code")`

## Interface Contract

```
INPUTS:
  ticket_id: str               — e.g. GH-172, FEAT-300
  spec_path: Path | None       — defaults to docs/specs/<TICKET-ID>.md
  project_root: Path | None    — defaults to repo root (cwd)
  check_only: bool             — true returns the drift report
                                 without writing; default false

OUTPUTS:
  drift_report: DriftReport    — list of structural / behavioural
                                 signals found
  spec_updated: bool           — true if the spec was rewritten

SIDE EFFECTS:
  - Modifies docs/specs/<TICKET-ID>.md when check_only is false
    and only structural drift exists
```

## Workflow

### Step 1: Locate the Canonical Spec

Resolve `spec_path` from `ticket_id` if not supplied:
`docs/specs/<TICKET-ID>.md`. If missing, **STOP** and ask the
user whether to run `Dev10x:ticket-scope` to create one.

### Step 2: Run the Drift Detector

Call the shared module via the CLI wrapper — inline `python -c`
is hook-blocked, and the CLI keeps both skills on one detector:

```bash
dev10x spec drift docs/specs/<TICKET-ID>.md --project-root .
```

Exit code `0` means no drift, `1` means structural drift only,
`2` means behavioural drift is present; each signal line is
printed as `[<kind>] <section>: <detail>`. The same detector is
used by `Dev10x:spec-update` — both skills agree on what counts
as drift.

**Gitignored spec warning.** If `docs/specs/` is listed in
`.gitignore`, the spec is local-only and invisible to CI — commit
it (drop the ignore rule) or explicitly warn the user that no
teammate or CI run will see the drift check.

### Step 3: Branch on Drift Kind

**REQUIRED: Call `AskUserQuestion`** when both kinds exist —
plain text would silently default to "sync structural only" and
let the behavioural drift slip through.

| Report state | Action |
|--------------|--------|
| `not report.has_drift` | STOP — no work to do. Mark task completed. |
| `report.has_behavioural` only | DELEGATE — `Skill("Dev10x:spec-update", ...)` and exit. |
| `report.has_structural` only | PROCEED — Step 4 regenerates structural sections. |
| Both kinds present | ASK the user (gate below) — proceed with structural-only sync, run spec-update first, or split into two steps. |

**Gate options** (when both drift kinds are present):

- **Run spec-update first (Recommended)** — Behavioural drift is
  the more dangerous kind; resolve it before touching structure.
- **Sync structural only, escalate behavioural** — Write the
  structural updates and surface the behavioural signals as a
  ticket comment / TODO for follow-up.
- **Abort** — Investigate manually before either path runs.

If `check_only=True`, **skip this gate** and return the report
unchanged. The caller (e.g., `gh-pr-respond`, `git-groom`)
decides what to do.

### Step 4: Regenerate Structural Sections

For each structural signal, locate the section it pertains to
(`Architecture`, `Implementation Steps`, `Code References`) and:

1. Re-derive the section's content from the current code (read
   the referenced modules, inspect actual symbols, list current
   file paths).
2. Replace the section body using `Edit`. **Preserve sibling
   sections** (Requirements / Acceptance Criteria / Entities /
   Norms / Safeguards) byte-for-byte — those are the source of
   truth and should never change in a refactor sync.

### Step 5: Re-run the Detector

After rewriting, call `detect_drift` again. If structural drift
remains, surface it to the user — the regeneration was
incomplete. Do not auto-loop.

### Step 6: Mark Task Completed

If the spec was updated, commit the change with the ticket ID
and the gitmoji `📝` (docs). Per the project's git-commit
convention, the title outcome-focuses on the spec, not the
underlying refactor:

> `📝 <TICKET-ID> Resync spec Architecture with refactored module layout`

## Decision Gates

This skill has **one REQUIRED `AskUserQuestion` gate** at Step 3
when both drift kinds are present. See `.claude/rules/skill-gates.md`.

## Integration Points

- **`Dev10x:spec-update`** — inverse path (behaviour-first).
  Shares `dev10x.spec.drift_detector`.
- **`Dev10x:ticket-scope`** — creates the canonical spec.
- **`Dev10x:gh-pr-respond`** (GH-173) — calls this skill in
  `check_only=True` mode before applying review-comment fixups.
- **`Dev10x:git-groom`** (GH-173) — pre-merge guard.

## Anti-Patterns

- ❌ Editing Requirements / Acceptance Criteria / Safeguards in
  a structural sync — those sections are owned by
  `Dev10x:spec-update`. Touching them here causes the
  contradiction the shared detector exists to prevent.
- ❌ Skipping the post-rewrite re-run (Step 5). Without the
  re-check, the skill cannot prove the drift was actually fixed.
- ❌ Calling this skill on a behavioural change "to update the
  spec quickly". Behavioural changes must go through
  `Dev10x:spec-update` so the spec is updated **before** the
  code, not after.

## References

- ADR 0005 — SPDD pipeline rationale (canonical detector,
  two entry points)
- `src/dev10x/spec/drift_detector.py` — shared module
- `references/skill-pipelines.md` — Structured Spec Pipeline
  (added in GH-175)
