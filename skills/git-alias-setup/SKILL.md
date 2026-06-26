---
name: Dev10x:git-alias-setup
description: >
  Set up git aliases that reduce permission friction by wrapping
  $(git merge-base ...) subshells into stable command prefixes.
  TRIGGER when: SessionStart reports missing aliases, or user hits
  permission friction from subshell-based git commands.
  DO NOT TRIGGER when: aliases already configured (check git config).
user-invocable: true
invocation-name: Dev10x:git-alias-setup
allowed-tools:
  - mcp__plugin_Dev10x_cli__setup_aliases
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/git-alias-setup/scripts/git-alias-setup.sh)
---

**Announce:** "Using Dev10x:git-alias-setup to configure branch-comparison aliases."

# Dev10x:git-alias-setup — Git Alias Configuration

Configures global git aliases that wrap `$(git merge-base ...)` subshells.
Without these aliases, commands like `git log $(git merge-base develop HEAD)..HEAD`
trigger extra permission prompts because the `$()` substitution shifts
the Bash command prefix.

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Create a task at invocation, mark completed when done:

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Configure git aliases", activeForm="Configuring aliases")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Usage

Run the setup script:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/git-alias-setup/scripts/git-alias-setup.sh
```

## Aliases Configured

`git nopager` / `git nocolor` are the sanctioned non-paging / non-color
reads — use them instead of the `git -c core.pager=cat <verb>` and
`git -c color.ui=never <verb>` prefixes that DX007 blocks (the `-c <kv>`
prefix shifts the matched command string, GH-488 S19).

Each base branch gets three comparison aliases (`{base}-log`, `{base}-diff`,
`{base}-rebase`) plus a non-interactive autosquash alias (`autosquash-{base}`).

| Alias                | Equivalent                                                  |
|----------------------|-------------------------------------------------------------|
| `git nopager <verb>` | `git --no-pager <verb>` (non-paging read; matches `Bash(git nopager:*)`) |
| `git nocolor <verb>`  | `git -c color.ui=never <verb>` (non-color read; matches `Bash(git nocolor:*)`) |
| `git develop-log`    | `git log --oneline $(git merge-base develop HEAD)..HEAD`    |
| `git develop-diff`   | `git diff $(git merge-base develop HEAD)..HEAD`             |
| `git develop-rebase` | `git rebase -i --autosquash $(git merge-base develop HEAD)` |
| `git autosquash-develop` | `GIT_SEQUENCE_EDITOR=true git rebase -i --autosquash $(git merge-base origin/develop HEAD)` |
| `git development-log`    | `git log --oneline $(git merge-base development HEAD)..HEAD`    |
| `git development-diff`   | `git diff $(git merge-base development HEAD)..HEAD`             |
| `git development-rebase` | `git rebase -i --autosquash $(git merge-base development HEAD)` |
| `git autosquash-development` | `GIT_SEQUENCE_EDITOR=true git rebase -i --autosquash $(git merge-base origin/development HEAD)` |
| `git trunk-log`      | `git log --oneline $(git merge-base trunk HEAD)..HEAD`      |
| `git trunk-diff`     | `git diff $(git merge-base trunk HEAD)..HEAD`               |
| `git trunk-rebase`   | `git rebase -i --autosquash $(git merge-base trunk HEAD)`   |
| `git autosquash-trunk` | `GIT_SEQUENCE_EDITOR=true git rebase -i --autosquash $(git merge-base origin/trunk HEAD)` |
| `git main-log`       | `git log --oneline $(git merge-base main HEAD)..HEAD`       |
| `git main-diff`      | `git diff $(git merge-base main HEAD)..HEAD`                |
| `git main-rebase`    | `git rebase -i --autosquash $(git merge-base main HEAD)`    |
| `git autosquash-main` | `GIT_SEQUENCE_EDITOR=true git rebase -i --autosquash $(git merge-base origin/main HEAD)` |
| `git master-log`     | `git log --oneline $(git merge-base master HEAD)..HEAD`     |
| `git master-diff`    | `git diff $(git merge-base master HEAD)..HEAD`              |
| `git master-rebase`  | `git rebase -i --autosquash $(git merge-base master HEAD)`  |
| `git autosquash-master` | `GIT_SEQUENCE_EDITOR=true git rebase -i --autosquash $(git merge-base origin/master HEAD)` |

## When to Use

The session start hook checks for these aliases automatically.
If they are missing, it will suggest running this skill.

After setup, use `git {base}-log` instead of the full subshell form
in all git operations to avoid permission friction.

## Scope

Aliases are set globally (`--global`) so they persist across all
repositories and sessions.
