---
name: Dev10x:git-commit
description: >
  Create a properly formatted git commit following project conventions
  (gitmoji, ticket reference, 72 char limit). Extracts ticket ID from
  branch name, prompts for description and solution points, stages
  changes, and creates the commit.
  TRIGGER when: creating a git commit with proper formatting.
  DO NOT TRIGGER when: amending commits, creating fixup! commits (use
  Dev10x:git-fixup), or splitting commits (use Dev10x:git-commit-split).
user-invocable: true
invocation-name: Dev10x:git-commit
allowed-tools:
  - AskUserQuestion
  - mcp__plugin_Dev10x_cli__mktmp
  - mcp__plugin_Dev10x_cli__plan_sync_json_summary
  - Bash(/tmp/Dev10x/bin/mktmp.sh:*)
  - Write(/tmp/Dev10x/git/**)
---

# Create Commit

Create properly formatted git commits with gitmoji, ticket
reference, 72-char title limit, structured body, and outcome-
focused titles (JTBD style).

## Instructions

The full workflow — 12 steps covering branch validation, ticket
extraction, commit type, description prompts, solution points,
line-length validation, staging, and commit creation — lives in
[`instructions.md`](instructions.md).

When this skill is invoked, Read `instructions.md` now and
follow it end-to-end. `AskUserQuestion` gates documented there
are REQUIRED.
