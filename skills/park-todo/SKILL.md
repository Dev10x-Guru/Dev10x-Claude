---
name: Dev10x:park-todo
description: >
  Defer work to code or session-level storage — so items resurface
  when editing nearby code or starting a new session in the same
  project, instead of being forgotten.
  TRIGGER when: deferring work to code comments or the project
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
  - mcp__plugin_Dev10x_cli__task_index_append
  - mcp__plugin_Dev10x_cli__task_index_get
---

# Dev10x:park-todo — Persistent Code/Session Deferrals

**Announce:** "Using Dev10x:park-todo to [add TODO/FIXME to code | append item to the task index]."

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Create a task at invocation, mark completed when done:

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Create deferred TODO", activeForm="Creating TODO")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Overview

Write deferred items to persistent storage where they will be
rediscovered by humans or Claude in the right context.

The canonical task index is the per-repo store behind
`mcp__plugin_Dev10x_cli__task_index_append` (GH-85, rehomed in
GH-1009). Every project deferral appends an entry to its `tasks:`
list so `Dev10x:park-discover` surfaces it on the next session start.

**Never Write/Edit the index file directly.** It used to live at
`.claude/Dev10x/session.yaml`; ADR-0018 D5 moved it out of the repo
because a Write/Edit under a project's `.claude/` trips Claude Code's
self-settings consent gate on every session, regardless of allow
rules. The MCP tool writes it from the server process, so no gate
fires — and it is keyed by the repo's git common dir, so an item
parked in one worktree resurfaces in every sibling checkout.

## Modes

### 1. Inline Code (TODO / FIXME)

When a specific file and location are relevant, insert a comment
directly in the code AND index it in the task index so the
discovery skill can find it without grepping `src/`.

- `# TODO: message` — actionable, expected soon (this PR, next session)
- `# FIXME: message` — known issue, no timeline, boy scout rule applies

**How to insert:**

1. Read the target file
2. Use Edit to insert the comment at the appropriate line
3. Append an index entry (see § Task Index Append) with
   `source: code-todo` and `metadata.location: "<path>:<line>"`
4. Report what was added and where

**Example:**

```python
# TODO: Configure webhook secret from dashboard before going live
WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
```

### 2. Project Task Index

When no specific file is relevant, append to the task index's
`tasks:` list with `source: park` so `Dev10x:park-discover`
finds it.

This replaces the pre-GH-85 `.claude/TODO.md` file. The TODO
file is still read by `Dev10x:park-discover` for back-compat,
but new items are written to the task index.

## Task Index Append

Call `mcp__plugin_Dev10x_cli__task_index_append` with one `entry`
object. `subject` and `source` are required — the tool rejects an
entry without them, because an unattributed entry cannot be grouped
in `Dev10x:park-discover`'s per-writer report:

```
mcp__plugin_Dev10x_cli__task_index_append(entry={
    "subject": "<one-line description>",
    "status": "pending",
    "source": "<code-todo | park>",
    "created_at": "<YYYY-MM-DD>",
    "metadata": {
        "branch": "<current-branch>",
        "location": "<file:line>",   # only for source: code-todo
    },
})
```

**Append rules:**

1. One call per deferral. The tool appends to the END of the `tasks:`
   list under a file lock, so concurrent parks from parallel
   worktrees cannot lose each other's entry.
2. Do NOT read-modify-write the store yourself. The tool owns the
   read-modify-write cycle; doing it by hand reintroduces both the
   lost-update race and the self-settings gate.
3. On the first append after the GH-1009 rehome, the tool folds any
   entries still sitting in the retired `.claude/Dev10x/session.yaml`
   forward automatically and reports the file in `folded_legacy` —
   nothing parked before the move is orphaned.

**Retired durable keys are not the index's business.** `friction_level`
and `active_modes` are durable preferences that live in
`~/.config/Dev10x/friction.yaml` (ADR-0018 D1); the tool never reads
or writes them, so there is nothing to preserve while appending.

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
- `Dev10x:session-wrap-up` — Phase 1 reads the task index `tasks:`
  via `mcp__plugin_Dev10x_cli__task_index_get` for existing items
  (and the legacy `.claude/TODO.md` for back-compat)
