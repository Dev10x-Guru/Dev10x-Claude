---
name: dev10x:ci-review
description: >
  Use when a change to a Claude CI review prompt, args file, reviewer
  agent or CLI pin needs checking before it merges — so you read what
  the CI code review and PR hygiene check would post on a real PR,
  without anything reaching GitHub.
  TRIGGER when: "what would the CI review say", replaying the Claude CI
  review locally, verifying a review prompt or model change on a PR.
  DO NOT TRIGGER when: self-reviewing a branch with no PR (use
  dev10x:review), or reviewing someone's PR and posting (use
  dev10x:gh-pr-review).
user-invocable: true
invocation-name: dev10x:ci-review
allowed-tools:
  - AskUserQuestion
  - Bash(uvx dev10x ci-review:*)
  - mcp__plugin_dev10x_cli__pr_detect
---

# dev10x:ci-review

**Announce:** "Using dev10x:ci-review to replay the Claude CI review
locally on PR #<N>."

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Replay CI review on PR #<N>", activeForm="Replaying CI review")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Overview

`dev10x ci-review` reads `.github/workflows/claude-code-review.yml` and
`claude-pr-hygiene.yml` and does what they do:

- checks out `refs/pull/<N>/merge`;
- stages the base-owned prompt, args and rules;
- replays the action's `restoreConfigFromBase`;
- prefetches the PR context;
- runs the pinned CLI with an empty config;
- replays the post-steps.

Every GitHub write the run attempts goes to an outbox instead of
posting. The skill wraps the command. It never posts to GitHub.

It cannot reproduce the bot identity, check runs, the
`pull_request` trigger, the CI token's scope or model nondeterminism.
Two runs on the same PR can differ.

## Workflow

### Step 1: Resolve the PR

Take the PR number or URL from the arguments. With none, call
`mcp__plugin_dev10x_cli__pr_detect` for the current branch's PR. A
branch with no PR has no CI review to replay; point to
`dev10x:review` and stop.

### Step 2: Render (free)

```bash
uvx dev10x ci-review --pr <N> --workflow all --render-only
```

Show the guard verdicts, the pinned CLI version and the rendered
prompt's location. A failed guard (draft, fork, not open) means CI
would skip this PR. Report which guard failed and stop. Pass
`--rules head` only when the user wants the PR's own prompts and
rules instead of the base branch's.

### Step 3: Confirm the paid run

A model run costs money: real API spend with `ANTHROPIC_API_KEY` set,
and subscription usage (notional cost) otherwise. Never start one
without an answer, in any session mode.

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text). This
blocks execution until the user responds. Options:

- Run both reviews (Recommended): code review, then hygiene
- Run the code review only
- Run the hygiene check only
- Stop at the render

### Step 4: Run

```bash
uvx dev10x ci-review --pr <N> --workflow <all|code-review|hygiene>
```

Pass the same `--rules` value as Step 2.

### Step 5: Present

Relay the command's report:

- the inline comments as `path:line` with each one's first line;
- the would-be `gh` writes (review summary, draft conversion, hygiene
  comment);
- the usage table, labeled notional when it ran on a subscription;
- the run directory, which holds `outbox.jsonl` and `execution.json`.

Say plainly that nothing was posted.
