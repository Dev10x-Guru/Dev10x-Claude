---
name: Dev10x:gh-pr-bookmark
description: >
  Post a rich session bookmark comment on a PR — captures session ID,
  review thread status, current state, and next steps so the next
  session can pick up where this one left off.
  TRIGGER when: pausing or ending session with an open PR that has
  in-progress work.
  DO NOT TRIGGER when: no PR exists, or session-wrap-up handles
  bookmarking automatically.
user-invocable: true
invocation-name: Dev10x:gh-pr-bookmark
allowed-tools:
  - mcp__plugin_Dev10x_cli__pr_detect
  - Skill(Dev10x:park)
---

# Dev10x:gh-pr-bookmark — PR Session Bookmark

**Announce:** "Using Dev10x:gh-pr-bookmark to save session state to the PR."

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Create a task at invocation, mark completed when done:

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Post PR session bookmark", activeForm="Bookmarking PR")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Overview

Thin wrapper around `Dev10x:park` that pre-selects the **PR session
bookmark** target. Use at end-of-session or when pausing work on a PR.
`Dev10x:park` posts the comment AND appends a `source: pr-bookmark`
entry to `.claude/Dev10x/session.yaml` so the bookmark is discoverable
locally by `Dev10x:park-discover` (GH-85).

## Workflow

### 1. Detect PR

```
mcp__plugin_Dev10x_cli__pr_detect(arg="")
```

The MCP wrapper resolves the current branch's PR. Treat an
`{"error": ...}` response as "no open PR" — tell the user and stop.

### 2. Delegate to Dev10x:park

Invoke `Dev10x:park` with:
- **Item**: the user's description (or "Continuing PR review" if none)
- **Pre-selected target**: `PR session bookmark`

Skip the target selection prompt — this skill always routes to the
PR session bookmark target in `Dev10x:park`.

### 3. Done

`Dev10x:park` handles data gathering, composition, posting, and
confirmation.

## Usage

```
/Dev10x:gh-pr-bookmark                          # bookmark current PR
/Dev10x:gh-pr-bookmark Wait for CI then merge   # bookmark with custom note
```

## See Also

- `Dev10x:park` — full deferral router with all targets
- `Dev10x:session-wrap-up` — end-of-session orchestrator that may call this
