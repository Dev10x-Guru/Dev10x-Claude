---
name: Dev10x:session-tasks
description: >
  Track in-session work items — so open loops are visible and triageable
  before session end without losing track of parallel work.
  TRIGGER when: managing in-session task tracking, viewing open loops,
  or adding work items mid-session.
  DO NOT TRIGGER when: starting structured work from inputs (use
  Dev10x:work-on), or wrapping up a session (use Dev10x:session-wrap-up).
user-invocable: true
invocation-name: Dev10x:session-tasks
---

# Dev10x:session-tasks — In-Session Task Tracking

**Announce:** "Using Dev10x:session-tasks to [show/add/update] session tasks."

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Create a task at invocation, mark completed when done:

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Track session work items", activeForm="Tracking items")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Overview

Thin wrapper around Claude's `TaskCreate`/`TaskUpdate`/`TaskList` tools
for tracking work items within the current session.

## Auto-Advance

After creating tasks via this skill, **immediately start
executing the first pending task**. Do not pause to ask
"should I start?" or wait for the user to say "go". The act
of creating the task list is the authorization to begin.

```
TaskCreate(subject="Task 1", ...)
TaskCreate(subject="Task 2", ...)
TaskUpdate(taskId=task1, status="in_progress")
# Begin working on Task 1 immediately
```

This follows the universal auto-advance rule from
`references/task-orchestration.md`.

## Commands

### Show tasks

Use `TaskList` to display all current tasks grouped by status.
Present as a markdown table:

| # | Status | Task |
|---|--------|------|
| 1 | in_progress | Implement checkout feature |
| 2 | pending | Create PR for TICKET-42 |
| 3 | completed | Add webhook endpoint |

### Add task

Use `TaskCreate` with:
- `subject`: short task title
- `description`: context, file paths, or links if available

### Update task

Use `TaskUpdate` with the task ID and new `status`:
- `in_progress` — currently working on
- `completed` — done
- `pending` — deferred within this session

## Task List Invariant (GH-149)

The session task list must never be empty. When all work items are
`completed`, this skill MUST seed a `Verify AC and close session`
task before returning control to the supervisor:

```
TaskCreate(subject="Verify AC and close session",
    description="<summary of shipped changes, PR links, CI status>",
    activeForm="Verifying AC")
```

See `.claude/rules/essentials.md` § Task List Invariant for the full
contract. Standalone `session-tasks` invocations that find an empty
task list at the end MUST create this task before completing — a
new prompt arriving on an empty list competes for attention with
whatever is in flight; with `Verify AC` present, the new prompt
lands as a TODO under the existing plan.

## Used By

- `Dev10x:park` — when user picks "keep for this session"
- `Dev10x:session-wrap-up` — Phase 1 auto-scan reads the task list
- `Dev10x:verify-acc-dod` — owns the `Verify AC` task completion
