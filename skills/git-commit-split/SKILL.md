---
name: Dev10x:git-commit-split
description: >
  Split monolithic git commits into atomic, cohesive commits following
  Clean Architecture principles. Uses interactive rebase to separate
  changes by feature dependency order (utilities → data → DTOs →
  refactoring → features → API), ensuring each commit is self-contained,
  passes tests, and maintains proper cohesion.
  TRIGGER when: a commit contains mixed concerns that should be separate
  atomic commits.
  DO NOT TRIGGER when: commits are already atomic, or grooming history
  without splitting (use Dev10x:git-groom).
user-invocable: true
invocation-name: Dev10x:git-commit-split
allowed-tools:
  - AskUserQuestion
  - mcp__plugin_Dev10x_cli__start_split_rebase
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/git-commit-split/scripts/:*)
---

# Split Commit Skill

Split monolithic git commits into atomic, cohesive commits that
follow Clean Architecture principles and dependency order. Each
resulting commit is self-contained, passes all tests, and
changes one well-scoped part of the code.

## Instructions

The full workflow — split-plan construction, interactive rebase
steps, per-commit validation, reorder rules — lives in
[`instructions.md`](instructions.md).

When this skill is invoked, Read `instructions.md` now and
follow it end-to-end. `TaskCreate` calls and the split-plan
`AskUserQuestion` gate documented there are REQUIRED.

## Invoke First, Not After Manual Steps (GH-160)

**As soon as the user — or the orchestrator — decides a commit
should be split into multiple atomic commits, this skill is the
first tool to reach for.** Audit GH-160 caught a session where
the agent attempted a manual split via 25 sequential
`git reset HEAD` + selective `git add` + `git commit -F` actions
across ~50 turns before eventually invoking the skill anyway,
making the cleanup harder than the original task.

The skill exists specifically to plan the split, run the
interactive rebase, validate per-commit, and reorder by
dependency. Do NOT improvise an equivalent manually:

- ❌ `git reset HEAD~N` + selective `git add` + N × `git commit -F`
- ❌ `git rebase -i HEAD~N` with `edit` directives, hand-edited
- ✅ `Skill(Dev10x:git-commit-split)` — single entry point

If you catch yourself reaching for `git reset HEAD` to "manually
group" staged files into separate commits, STOP and invoke this
skill instead.
