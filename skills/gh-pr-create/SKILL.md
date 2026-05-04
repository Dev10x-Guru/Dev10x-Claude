---
name: Dev10x:gh-pr-create
description: >
  Create a GitHub pull request for the current branch with issue tracker
  integration (GitHub Issues, Linear, or JIRA). Sources or generates a JTBD
  Job Story for the PR description, extracts ticket info from branch name,
  pushes the branch, creates a draft PR with Job Story, commit list, and
  issue tracker link, posts summary comment, and opens in browser.
  TRIGGER when: branch is ready for PR creation, user says "create PR".
  DO NOT TRIGGER when: PR already exists (use Dev10x:gh-pr-respond or
  Dev10x:gh-pr-monitor instead), or user just wants to push changes.
user-invocable: true
invocation-name: Dev10x:gh-pr-create
allowed-tools:
  - AskUserQuestion
  - mcp__plugin_Dev10x_cli__detect_base_branch
  - mcp__plugin_Dev10x_cli__verify_pr_state
  - mcp__plugin_Dev10x_cli__pre_pr_checks
  - mcp__plugin_Dev10x_cli__create_pr
  - mcp__plugin_Dev10x_cli__update_pr
  - mcp__plugin_Dev10x_cli__generate_commit_list
  - mcp__plugin_Dev10x_cli__post_summary_comment
  - mcp__plugin_Dev10x_cli__detect_tracker
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-create/scripts/:*)
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/gh-context/scripts/:*)
---

# Create Pull Request for Ticket

Create a GitHub pull request for the current branch with issue
tracker integration (GitHub Issues, Linear, or JIRA). Handles
pushing the branch, generating Job Story + commit list body,
creating the PR, posting summary comments, and opening it in
the browser. Supports update mode for existing PRs.

## Instructions

The full workflow — branch push, Job Story sourcing, PR body
template, ticket detection, preview gate, summary comment —
lives in [`instructions.md`](instructions.md).

When this skill is invoked, Read `instructions.md` now and
follow it end-to-end. `TaskCreate` and `AskUserQuestion` calls
documented there are REQUIRED (unless invoked with
`--unattended`, which auto-advances the preview gate).
