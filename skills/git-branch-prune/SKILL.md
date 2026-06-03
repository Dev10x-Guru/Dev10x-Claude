---
name: Dev10x:git-branch-prune
description: >
  Classify and prune stale local branches with merge verification,
  designed for rebase-merge repos where `git branch --merged` misses
  most merged branches.
  TRIGGER when: local repo has accumulated stale branches after fanout
  sessions, worktree cleanup, or manual sweeps.
  DO NOT TRIGGER when: working on a clean repo with few branches or
  when branch deletion is handled by another skill (e.g. Dev10x:fanout
  teardown).
user-invocable: true
invocation-name: Dev10x:git-branch-prune
allowed-tools:
  - AskUserQuestion
  - mcp__plugin_Dev10x_cli__detect_base_branch
  - Bash(git fetch --prune:*)
  - Bash(git branch:*)
  - Bash(git worktree list:*)
  - Bash(git log:*)
  - Bash(git worktree prune:*)
  - Bash(git rev-parse:*)
  - Bash(git merge-base:*)
---

# Git Branch Prune

Classify and prune stale local branches with merge verification.
Handles repos that rebase-merge (tip of merged branch is NOT an
ancestor of develop), where the naive `git branch --merged` + `grep
': gone]'` pipeline misses most stale branches.

## Overview

**Why the naive pipeline fails in rebase-merge repos:**

- `gone` tracking catches only branches whose remote was deleted on
  merge — usually a minority of stale branches.
- `git branch --merged develop` misses rebased commits because the
  tip is typically not an ancestor of develop after a rebase-merge.
- Never-pushed worktree branches (e.g. `worktree-agent-*`) have no
  upstream at all, so they never appear as `gone`.

This skill implements a validated 4-category classification that
catches all three failure modes while surfacing branches with real
unpublished work.

## Orchestration

**REQUIRED: Create tasks before ANY work.** Execute these
`TaskCreate` calls at startup:

1. `TaskCreate(subject="GH-464 Classify and prune stale branches",
   activeForm="Classifying branches")`

Mark completed when done:
`TaskUpdate(taskId, status="completed")`

**Announce:** "Using Dev10x:git-branch-prune to classify and prune
stale local branches."

## Workflow

### Step 1: Detect Base Branch

Call `mcp__plugin_Dev10x_cli__detect_base_branch` to determine the
base branch (prefers `develop`/`development`, falls back to
`main`/`master`/`trunk`). Use this throughout — never hardcode
`develop`.

### Step 2: Fetch and Prune Remotes

Run `git fetch --prune` to remove stale remote-tracking refs before
classification.

### Step 3: Collect Live Worktrees

Run `git worktree list --porcelain` and extract the `HEAD` commit
SHA for each worktree path. A branch checked out in a live worktree
must never be deleted — skip any branch whose tip SHA matches a live
worktree HEAD.

### Step 4: Classify Each Local Branch

Skip the following branches unconditionally:
- The currently checked-out branch
- `main`, `master`, `develop`, `development`, `trunk`
- Any branch checked out in a live worktree (Step 3)

For each remaining branch, apply this decision tree in order:

**Category A — `gone` upstream (safe `-D`):**
`git branch -vv` shows `: gone]` — remote was deleted (typically
on merge via GitHub). Safe to delete with `git branch -D`.

**Category B — no upstream, tip is ancestor of base (safe `-d`):**
Branch has no upstream (`git branch -vv` shows no `[...]` tracking
info) AND `git merge-base --is-ancestor <tip> origin/<base>` returns
0. Zero unique commits — safe to delete with `git branch -d`.

**Category C — no upstream, tip not ancestor, content-matched
(safe `-D` after verification):**
Branch has no upstream AND the tip is NOT an ancestor of base.
Run rebase-merge content check:
`git log origin/<base>..HEAD --oneline` lists commits unique to
this branch. For each unique commit, check whether its title or a
TICKET-ID from the branch name appears in
`git log origin/<base> --oneline --grep=<subject>`. If all unique
commits are found (content landed on base), safe to delete with
`git branch -D`. If content check fails, move to Category D.

**Category D — keep and surface:**
All other branches: tracking a live upstream with `ahead N`
commits, or content-check failed (Category C fallback), or
undecidable state. Do NOT delete. Surface to user with reason.

### Step 5: Present Categories and Request Approval

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
Present the classified branch list and ask the user to approve
deletions per category:

Gate options (present all four options):
- **Delete A + B + C** — Remove all auto-safe and
  content-verified branches (recommended when C list was
  inspected and looks correct)
- **Delete A + B only** — Remove only unambiguously safe
  branches; inspect Category C manually first
- **Delete A only** — Remove only `gone`-upstream branches;
  most conservative
- **Skip all deletions** — Exit without deleting anything;
  just show the report

Include in the gate presentation:
- Count per category (e.g. "Category A: 14 branches")
- Full branch names per category, formatted as a code block
- Category D branches with per-branch reason for keeping

### Step 6: Execute Approved Deletions

Delete branches in the approved categories using the appropriate
flag:
- Category A and C: `git branch -D <name>` (force-delete)
- Category B: `git branch -d <name>` (safe-delete)

Catch and report any deletion errors individually — do not abort
the batch on a single failure.

### Step 7: Cleanup

Run `git worktree prune` to remove stale worktree administrative
files.

If `git` warned about unreachable loose objects during any of the
above steps, suggest the user run `git prune` separately (do not
run it automatically — it can be slow on large repos).

### Step 8: Report

Print a summary:
- Branches deleted per category
- Branches kept (Category D) with reasons
- Any deletion errors

Mark the task completed.

## Integration Note (GH-463)

The Dev10x:fanout skill's worktree teardown step may delegate its
per-session branch-deletion to this skill in a future iteration.
This skill is designed for standalone invocation and does not
require or import any fanout-specific state.

## Anti-Patterns

- Never delete the currently checked-out branch.
- Never delete branches checked out in live worktrees.
- Never run `git branch -D` on a Category D branch without explicit
  user confirmation beyond the Step 5 gate.
- Never hardcode `develop` — always use the detected base branch.
- Do NOT run `git prune` automatically — suggest it only when gc
  warns.
