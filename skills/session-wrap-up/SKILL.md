---
name: Dev10x:session-wrap-up
description: >
  Capture and route unfinished work at session end — so nothing is
  lost when the session closes.
  TRIGGER when: session ending, user says "wrap up" / "pause" / "done
  for today", or too many open loops pile up.
  DO NOT TRIGGER when: mid-session active work with manageable task
  list, or starting new work (use Dev10x:work-on).
user-invocable: true
invocation-name: Dev10x:session-wrap-up
allowed-tools:
  - Bash(gh pr list:*)
---

# Dev10x:session-wrap-up — Session End Orchestrator

**Announce:** "Using Dev10x:session-wrap-up to capture open loops
before closing this session."

## Overview

Collect all open loops, present them to the user, and help defer
each one to the right discovery context.

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**Auto-advance:** Complete each step, immediately start the next.
Never pause to ask "should I continue?" between steps.

**REQUIRED: Create tasks before ANY work.** Execute these
`TaskCreate` calls at startup:

1. `TaskCreate(subject="Discover open items", activeForm="Scanning for open loops")`
2. `TaskCreate(subject="Route deferred items", activeForm="Routing deferred items")`
3. `TaskCreate(subject="Post session summary", activeForm="Posting summary")`

Set dependencies: route blocked by discover, summary blocked by
route. Update status as each completes.

## Phase 1: Auto-Scan

Run all scans silently, collecting results into a structured list.

### 1a. In-session tasks

Use `TaskList` to get all tasks. Filter for non-completed tasks.

### 1b. Git status

```bash
git status --short
```

Summarize: N uncommitted files, N staged files, N untracked files.
Group by directory for readability.

### 1c. Session TODOs

```bash
git diff HEAD --unified=0
```

Scan the diff for any `# TODO:` or `# FIXME:` lines added in this
session (lines starting with `+` that contain TODO or FIXME).

### 1d. Open PRs

```bash
gh pr list --head "$(git branch --show-current)" --state open \
  --json number,title,url --limit 5
```

### 1e. Project TODO file

Read `.claude/TODO.md` if it exists. Extract pending items (lines
matching `- [ ]`).

### 1f. MEMORY.md in-progress section

Read the project MEMORY.md. Extract items under "## In-progress work"
heading if present.

## Phase 2: Present & Gap-Fill

Present all discovered open loops in a scannable format:

```markdown
## Session Wrap-up — Open Loops Found

### In-session tasks (N)
• [status] Task description

### Git status
• N uncommitted files in path/to/dir/

### TODOs added this session (N)
• file.py:LINE: TODO description

### Open PRs (N)
• #123: PR title (url)

### Project TODO items (N)
• Existing deferred item from previous session

---

Is there anything else to capture before closing?
```

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text)
to let the user add free-text items.

## Phase 3: Per-Item Triage

For each open loop, **REQUIRED: Call `AskUserQuestion`**
(do NOT use plain text) to present a choice:

**Options:**
- **Finish now** — keep as session task, continue working
- **Defer** — invoke `Dev10x:park` for target selection
- **Drop** — remove, no longer needed

If the user picks "Finish now" for any item, pause the wrap-up and
let them work. When they return, resume from where they left off.

If the user picks "Defer", invoke `Dev10x:park` with the item.

If the user picks "Drop", mark the task as completed via `TaskUpdate`
and move on.

## PR Reminder Format

When deferring an item by posting a reminder comment on an open PR,
use this standard prefix so `Dev10x:park-discover` §2f can discover it:

```markdown
🔖 **Session bookmark**

This is an automated self-reminder left by `Dev10x:session-wrap-up` for the
PR author to pick up in a future session.

**Current state:** <brief summary of where the PR stands>

**Next steps:**
- <actionable item 1>
- <actionable item 2>
```

The `🔖 **Session bookmark**` prefix on the first line is required —
`Dev10x:park-discover` scans for this exact pattern when checking open
PRs for deferred work.

## Phase 3b: Session State Persistence (GH-917)

**After triage, before summary**, persist session state to
`.claude/Dev10x/session.yaml` so a future session can resume
where this one left off.

**What to persist:**

1. **Uncompleted tasks** — serialize the pending/in-progress
   task list from `TaskList` as a `tasks:` array:
   ```yaml
   tasks:
     - subject: "Implement fix"
       status: pending
       metadata: {type: epic}
     - subject: "Monitor CI"
       status: in_progress
       metadata: {skills: [dev10x:gh-pr-monitor]}
   ```

2. **Continuation prompt** — generate a one-paragraph summary
   of what was in progress and what to do next. Store as
   `continuation_prompt:` in session.yaml. This bootstraps
   context after `/clear` or a new session.

3. **Collected insights** — any lessons learned, patterns
   discovered, or decisions made during the session that
   are not captured in code or commits. Store as
   `insights:` list.

**Read-before-write:** Preserve existing `friction_level`
and `active_modes` when updating session.yaml — only add
the new fields, never overwrite existing config.

**Integration with `/clear`:** After writing session.yaml,
inform the user: "Session state saved. To resume after
`/clear`, invoke `Dev10x:work-on` — it will detect the
saved state and offer to continue."

## Phase 4: Summary

After all items are triaged, present a brief summary:

```
## Wrap-up Complete

Finished: 2 items
Deferred: 3 items (2 → TODO.md, 1 → Slack)
Dropped: 1 item

Session is ready to close.
```

## Batch Mode

If the user has many items (>5), offer batch operations:

- "Defer all to .claude/TODO.md" — sends all remaining to project file
- "Defer all to Slack" — sends all as one combined Slack DM
- "Triage one by one" — standard per-item flow

## Used By

- Invoked directly by user: `/Dev10x:session-wrap-up`
- Can be suggested by Claude when detecting session-end signals
  (e.g., user says "that's it for today", "let's wrap up")
