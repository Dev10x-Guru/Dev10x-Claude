---
name: Dev10x:gh-pr-respond
description: >
  Validate and respond to PR review comments. Handles single comment
  (with follow-up offer) or batch mode for all unaddressed comments on
  a PR/review. Orchestrates Dev10x:gh-pr-triage and Dev10x:gh-pr-fixup.
  TRIGGER when: PR has review comments that need responses or fixes.
  DO NOT TRIGGER when: no review comments exist, or user wants to
  create a new PR (use Dev10x:gh-pr-create).
user-invocable: true
invocation-name: Dev10x:gh-pr-respond
allowed-tools:
  - AskUserQuestion
  - mcp__plugin_Dev10x_cli__pr_comment_reply
  - mcp__plugin_Dev10x_cli__pr_comments
  - mcp__plugin_Dev10x_cli__pr_detect
  - mcp__plugin_Dev10x_cli__pr_issue_comment
  - mcp__plugin_Dev10x_cli__resolve_gate
  - Bash(gh pr ready:*)
  - Bash(gh api graphql:*)
  - Bash(gh api repos/:*)
  - Bash(jq:*)
  - Skill(Dev10x:gh-pr-triage)
  - Skill(Dev10x:gh-pr-fixup)
  - Skill(Dev10x:git-groom)
  - Skill(Dev10x:gh-pr-monitor)
  - Skill(Dev10x:git)
  - Skill(Dev10x:gh-pr-merge)
  - Skill(Dev10x:ticket-create)
---

# Respond to PR Review Comments

Recommended entry point for all PR review comments. Orchestrates
the full pipeline: collect comments, triage each one, implement
fixes, reply, and resolve threads. Do not call
`Dev10x:gh-pr-fixup` or `Dev10x:gh-pr-triage` directly unless
you are handling the full pipeline yourself.

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
