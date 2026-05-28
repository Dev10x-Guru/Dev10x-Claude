---
name: Dev10x:park-todo
description: >
  Defer work to code or session-level storage — so items resurface
  when editing nearby code or starting a new session in the same
  project, instead of being forgotten.
  TRIGGER when: deferring work to code comments or the session.yaml
  task index.
  DO NOT TRIGGER when: deferring to Slack (use Dev10x:park-remind),
  or routing to the best destination automatically (use Dev10x:park).
user-invocable: true
invocation-name: Dev10x:park-todo
allowed-tools:
  - Read
  - Edit
  - Write
  - Bash(git branch:*)
  - Bash(git rev-parse:*)
---

# Dev10x:park-todo — Persistent Code/Session Deferrals

**Announce:** "Using Dev10x:park-todo to [add TODO/FIXME to code | append item to session.yaml]."

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Create a task at invocation, mark completed when done:

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Create deferred TODO", activeForm="Creating TODO")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Overview

Write deferred items to persistent storage where they will be
rediscovered by humans or Claude in the right context.

The canonical task index is `.claude/Dev10x/session.yaml` (GH-85).
Every project deferral appends an entry to its `tasks:` list so
`Dev10x:park-discover` surfaces it on the next session start.

## Modes

### 1. Inline Code (TODO / FIXME)

When a specific file and location are relevant, insert a comment
directly in the code AND index it in session.yaml so the
discovery skill can find it without grepping `src/`.

- `# TODO: message` — actionable, expected soon (this PR, next session)
- `# FIXME: message` — known issue, no timeline, boy scout rule applies

**How to insert:**

1. Read the target file
2. Use Edit to insert the comment at the appropriate line
3. Append an index entry to session.yaml (see § Session.yaml Append)
   with `source: code-todo` and `metadata.location: "<path>:<line>"`
4. Report what was added and where

**Example:**

```python
# TODO: Configure webhook secret from dashboard before going live
WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
```

### 2. Project Task Index (session.yaml)

When no specific file is relevant, append to the session.yaml
`tasks:` list with `source: park` so `Dev10x:park-discover`
finds it.

This replaces the pre-GH-85 `.claude/TODO.md` file. The TODO
file is still read by `Dev10x:park-discover` for back-compat,
but new items are written to session.yaml.

## Session.yaml Append

Use the Read tool to load the current
`.claude/Dev10x/session.yaml` (create if missing), then use
Write or Edit to add the new task entry. The schema for a
task entry is:

```yaml
tasks:
  - subject: <one-line description>
    status: pending
    source: <code-todo | park>
    created_at: <YYYY-MM-DD>
    metadata:
      branch: <current-branch>
      location: <file:line>   # only for source: code-todo
```

**Append rules:**

1. Read existing session.yaml. If absent, write a minimal
   shell preserving any sibling fields the writer should leave
   alone (`friction_level`, `active_modes`, `continuation_prompt`,
   `insights`).
2. Add the new entry to the END of the `tasks:` list — never
   replace or reorder existing entries.
3. Preserve YAML key order: top-level keys stay in their
   existing positions; only the new task is appended.

**Never overwrite** `friction_level`, `active_modes`,
`continuation_prompt`, or `insights` while appending tasks.

## Context Gathering

When invoked, auto-detect:
- Current branch: `git branch --show-current` (single Bash call)
- Repository root: `git rev-parse --show-toplevel` (single Bash call)
- Current date: derive from the session — the writer is invoked
  in-session, so the date is "today" without a `date` shell-out

## Review Mode Redirect

If the user asks about **existing** deferred items (e.g., "what's deferred",
"check for open items", "what do we have from yesterday"), invoke
`Dev10x:park-discover` instead of this skill. This skill is for *writing*
deferrals; `Dev10x:park-discover` is for *reading them back*.

## Used By

- `Dev10x:park` — when user picks "project task index" or "inline code"
- `Dev10x:session-wrap-up` — Phase 1 reads session.yaml `tasks:`
  for existing items (and the legacy `.claude/TODO.md` for
  back-compat)
