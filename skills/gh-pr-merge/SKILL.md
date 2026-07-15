---
name: Dev10x:gh-pr-merge
description: >
  Validate all pre-merge conditions and execute PR merge.
  Checks unresolved threads, CI status, draft state, mergeability,
  working copy, fixup commits, Fixes-linked scope delivery, and
  review approval before merging.
  TRIGGER when: PR is ready to merge and needs pre-merge validation.
  DO NOT TRIGGER when: PR is still draft, CI is failing, or review
  comments are unaddressed.
user-invocable: true
invocation-name: Dev10x:gh-pr-merge
allowed-tools:
  - AskUserQuestion
  - Bash(gh pr checks:*)
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-merge/scripts/:*)
  - mcp__plugin_Dev10x_cli__pr_detect
  - mcp__plugin_Dev10x_cli__pr_get
  - mcp__plugin_Dev10x_cli__unresolved_threads
  - mcp__plugin_Dev10x_cli__pr_comments
  - mcp__plugin_Dev10x_cli__check_top_level_comments
  - mcp__plugin_Dev10x_cli__merge_pr
  - mcp__plugin_Dev10x_cli__resolve_gate
  - Bash(gh repo view:*)
  - Bash(git status:*)
  - Bash(git log:*)
---

# Merge PR

Pre-merge validation gate that checks 9 conditions before
executing `gh pr merge`. Prevents premature merges by verifying
unresolved threads, CI, draft state, mergeability, working copy,
fixup commits, Fixes-linked scope delivery, and review approval.

## Instructions

The full workflow — 9 pre-merge checks, strategy selection from
project settings, merge execution, post-merge verification —
lives in [`instructions.md`](instructions.md).

When this skill is invoked, Read `instructions.md` now and
follow it end-to-end. `TaskCreate` and `AskUserQuestion` calls
documented there are REQUIRED.

## Skill Wrapper is Mandatory (GH-152)

**Hard rule:** Do NOT call `gh pr merge` directly. Every PR
merge MUST go through `Skill(Dev10x:gh-pr-merge)` so the
9-check pre-merge gate (unresolved threads, top-level
comments, inline review comments, Fixes-linked scope
delivery, CI buckets, draft state, mergeability, working
copy, review approval) runs. Audit
GH-152 caught a session where the agent ran
`gh pr merge <N> --rebase --delete-branch` directly after
partially reading this SKILL.md — only the CI check was
performed inline, every other check was skipped.

The PreToolUse hook blocks raw `gh pr merge` (extends the
existing blocks on `git commit`, `git push`, and `git
checkout -b`). The skill executes Step 5 via
`mcp__plugin_Dev10x_cli__merge_pr` (GH-232) — symmetric to
`create_pr` / `push_safe` — so the documented flow ships
through a structured MCP tool, not a caller-level bypass.
