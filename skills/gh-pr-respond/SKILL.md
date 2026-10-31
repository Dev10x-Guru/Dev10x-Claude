---
name: dev10x:gh-pr-respond
description: >
  Validate and respond to PR review comments. Handles single comment
  (with follow-up offer) or batch mode for all unaddressed comments on
  a PR/review. Orchestrates dev10x:gh-pr-triage and dev10x:gh-pr-fixup.
  TRIGGER when: PR has review comments that need responses or fixes.
  DO NOT TRIGGER when: no review comments exist, or user wants to
  create a new PR (use dev10x:gh-pr-create).
user-invocable: true
invocation-name: dev10x:gh-pr-respond
allowed-tools:
  - AskUserQuestion
  - mcp__plugin_dev10x_cli__pr_comment_reply
  - mcp__plugin_dev10x_cli__pr_comments
  - mcp__plugin_dev10x_cli__pr_detect
  - mcp__plugin_dev10x_cli__pr_issue_comment
  - mcp__plugin_dev10x_cli__resolve_gate
  - mcp__plugin_dev10x_cli__unresolved_threads
  - mcp__plugin_dev10x_cli__check_top_level_comments
  - Bash(gh pr ready:*)
  - Bash(gh api graphql:*)
  - Bash(gh api repos/:*)
  - Bash(jq:*)
  - Skill(dev10x:gh-pr-triage)
  - Skill(dev10x:gh-pr-fixup)
  - Skill(dev10x:git-groom)
  - Skill(dev10x:gh-pr-monitor)
  - Skill(dev10x:git)
  - Skill(dev10x:gh-pr-merge)
  - Skill(dev10x:ticket-create)
---

# Respond to PR Review Comments

Recommended entry point for all PR review comments. Orchestrates
the full pipeline: collect comments, triage each one, implement
fixes, reply, and resolve threads. Do not call
`dev10x:gh-pr-fixup` or `dev10x:gh-pr-triage` directly unless
you are handling the full pipeline yourself.

## Pre-read short-circuit (GH-1665 F3)

Before reading `instructions.md`, resolve the PR (from the input, or
`mcp__plugin_dev10x_cli__pr_detect`) and issue all three calls in one
turn — they are independent:

1. `mcp__plugin_dev10x_cli__unresolved_threads(repo=…, pr_number=…)`
2. `mcp__plugin_dev10x_cli__check_top_level_comments(repo=…, pr_number=…)`
   — this counts bot findings only, so it cannot see a human comment
3. `mcp__plugin_dev10x_cli__pr_comments(action="list", pr_number=…)`
   — confirm no unaddressed human top-level comments remain

When calls 1 and 2 return `count: 0` and call 3 shows no unaddressed
human top-level comment, say "nothing to respond to" and
return without reading `instructions.md`.
When any call reports an item, or any call errors, continue below —
an unreadable count is not evidence that nothing is open.
Skip this check when the input is a single comment URL: the comment
itself is the work.

## Instructions

The full workflow — single vs batch mode, triage routing, fixup
creation, thread resolution, parent detection — lives in
[`instructions.md`](instructions.md).

When this skill is invoked, Read `instructions.md` now and
follow it end-to-end. `TaskCreate` and `AskUserQuestion` calls
documented there are REQUIRED.

**End-to-end read enforcement (GH-166, GH-1279): this file may
not fit in one `Read`.** At ~57 KB it sits close enough to the
token cap a single call returns that a truncated `PARTIAL view`
is likely, and an agent that stops at the first page is working
from part of the contract while believing it holds all of it.

Keep issuing `Read(offset=…)` until you have reached the final
line. Do NOT substitute `Grep` or a single `Read(limit=…)` for
the missing pages: the mode split, the triage routing and the
thread-resolution rules are scattered through the body rather
than sectioned, so a truncated read drops whichever happens to
fall past the cut.

If you did not see the last line of the file, you have not read
the contract.
