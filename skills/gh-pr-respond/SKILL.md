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
