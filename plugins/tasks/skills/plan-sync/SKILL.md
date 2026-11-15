---
name: dev10x:plan-sync
description: >
  Reconcile persisted plan file with in-session task list.
  Detects divergences, recreates missing tasks, and updates
  plan context.
  TRIGGER when: session resumed after compaction and task list
  is empty or out of sync with the plan file.
  DO NOT TRIGGER when: no plan file exists or task list is
  already in sync with the current session work.
user-invocable: true
invocation-name: dev10x:plan-sync
allowed-tools:
  - TaskCreate
  - TaskList
  - TaskUpdate
  - Read
  - mcp__plugin_dev10x_cli__plan_sync_set_context
  - mcp__plugin_dev10x_cli__plan_sync_json_summary
  - mcp__plugin_dev10x_cli__plan_sync_archive
---

# Plan Sync — Reconcile Persisted Plan with Session State

## When to Use

- After context compaction when tasks may be missing
- When resuming a session and want to verify plan integrity
- When you suspect the persisted plan has drifted from session state
- To store plan context (work_type, routing table, gathered summary)

## Orchestration

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Sync plan state", activeForm="Syncing plan")`

## Workflow

### Step 1: Read Persisted Plan

Read the plan file at `<git-toplevel>/.claude/session/plan.yaml`.
If no plan file exists, report "No persisted plan found" and exit.

Extract:
- Plan metadata (branch, status, created_at)
- Plan context (work_type, routing_table, tickets, gathered_summary)
- Full task list with metadata

### Step 2: Read Session Task List

Call `TaskList` to get the current in-session task state.

### Step 3: Compare and Report

For each task in the persisted plan:
1. Find matching task in session by subject (fuzzy match)
2. Compare status — report mismatches
3. Identify tasks in plan but missing from session
4. Identify tasks in session but missing from plan

Report format:
```
Plan: 15 tasks | Session: 12 tasks

Matched (same status): 10
Status mismatch: 2
  - #5 "Set up workspace" — plan: completed, session: pending
  - #7 "Implement changes" — plan: in_progress, session: completed
Missing from session: 3
  - #13 "Groom commit history" (detailed) → git-groom
  - #14 "Update PR description" (detailed) → gh-pr-create
  - #15 "Mark PR ready" (detailed)
Extra in session: 0
```

### Step 4: Reconcile

For missing tasks, recreate them:
```
TaskCreate(subject=<from plan>, description=<from plan>,
    metadata=<from plan including type, skills, steps>)
```

For status mismatches, trust the session state (it's more
recent) and update the plan file via:
`mcp__plugin_dev10x_cli__plan_sync_set_context(args=["last_reconciled=<timestamp>"])`

### Step 5: Update Plan Context (Optional)

If the caller passes context arguments, store them:

`mcp__plugin_dev10x_cli__plan_sync_set_context(args=["work_type=feature", "tickets=[\"GH-482\"]", "routing_table={...}"])`

### Step 6: Archive (if all complete)

If all tasks in both plan and session are completed:
`mcp__plugin_dev10x_cli__plan_sync_archive()`

Report: "Plan archived. All tasks completed."
