---
name: dev10x:git-promote
description: >
  Convert existing git commits into issue tracker tickets with proper
  branch management and commit message formatting. Automates creating
  the ticket, branching, cherry-picking, and updating the commit message.
  TRIGGER when: a commit needs to be retroactively tracked with a ticket,
  typically for tech debt fixes, bug fixes, or improvements committed
  without a ticket reference.
  DO NOT TRIGGER when: commit already has a ticket reference, or creating
  a new ticket before committing (use dev10x:ticket-create).
user-invocable: true
invocation-name: dev10x:git-promote
allowed-tools:
  - Bash(git show:*)
  - Bash(git cherry-pick:*)
  - Bash(git log:*)
---

# Commit to Ticket

## Overview

This skill automates the process of converting an existing git commit into a tracked ticket with proper tracking. It creates a ticket from the commit's changes, creates a properly named branch, cherry-picks the commit, and updates the commit message to reference the new ticket.

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Create a task at invocation, mark completed when done:

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Promote commits to tickets", activeForm="Promoting commits")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Prerequisites Check

**IMPORTANT:** This skill uses the `dev10x:ticket-create` skill which supports GitHub Issues, Linear, and JIRA.

## When to Use This Skill

Use this skill when:
- A commit was made without a ticket reference
- Tech debt or bug fixes need to be tracked retroactively
- A commit needs proper documentation in the issue tracker
- A commit needs to be moved to a feature branch with ticket tracking

## Workflow

### Step 1: Show Recent Commits (if no commit hash provided)

If the user does not provide a commit hash, show the last 20 commits for selection:

```bash
git log --oneline -20
```

### Step 2: Analyze the Commit

Examine the commit to understand what problem it solves:

```bash
git show <commit-hash>
```

### Step 3: Create Ticket

Use the `dev10x:ticket-create` skill to create a properly structured ticket from the commit.

### Step 4: Create Branch

Use the `dev10x:ticket-branch` skill to create a properly named branch.

### Step 5: Cherry-pick Commit

Cherry-pick the original commit to the new branch:

```bash
git cherry-pick <commit-hash>
```

### Step 6: Update Commit Message

Amend the commit message to reference the new ticket.

### Step 7: Verify Result

Show the updated commit and verify changes.

### Step 8: Push and Create PR (Optional)

Use the `dev10x:gh-pr-create` skill to push the branch and create a PR.

## Integration with Other Skills

```
dev10x:git-promote
├── Uses: dev10x:ticket-create (Step 3)
├── Uses: dev10x:ticket-branch (Step 4)
└── Uses: dev10x:gh-pr-create (Step 8, optional)
```
