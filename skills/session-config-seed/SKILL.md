---
name: Dev10x:session-config-seed
description: >
  Seed the global ~/.config/Dev10x/friction.yaml (and the repo's
  .claude/Dev10x/.gitignore) when either is missing, so work-on /
  verify-acc-dod have a gate policy to resolve. Idempotent — existing
  files are preserved. TRIGGER when: a skill (e.g. work-on Phase 0)
  finds no friction policy for this checkout and needs a default before
  resolving gates. DO NOT TRIGGER when: the files already exist (the
  seed is a no-op), or you need to CHANGE an existing policy (use
  Dev10x:friction-setup or Dev10x:afk — this skill never overwrites).
user-invocable: true
invocation-name: Dev10x:session-config-seed
allowed-tools:
  - Bash(uvx dev10x session seed:*)
  - Bash(dev10x session seed:*)
---

**Announce:** "Using Dev10x:session-config-seed to seed session config."

# Dev10x:session-config-seed — Seed the gate policy when missing

Thin wrapper over `dev10x session seed`. The CLI does an idempotent
`O_EXCL` write of two things — so this skill is the agent-time
counterpart to the shell-only `post-checkout` hook (a git hook cannot
invoke a Claude skill, GH-705). Both call the same CLI, so seeding
behaves identically whether triggered at worktree creation (hook) or at
session start (this skill).

| Seeded | Purpose |
|--------|---------|
| `~/.config/Dev10x/friction.yaml` | Global, gate-free durable prefs — the `defaults` block a repo without a `projects[]` entry resolves against (ADR-0018) |
| `<repo>/.claude/Dev10x/.gitignore` | A single `*` so runtime artifacts under that directory never reach `git status` and trip the clean-tree gates in `verify_pr_state` / `Dev10x:gh-pr-merge` / `create_pr` (GH-809) |

Since ADR-0018 the per-repo `.claude/Dev10x/session.yaml` and
`config.yaml` are **retired**, so seed writes nothing durable under the
repo's `.claude/` tree — which is why it never trips Claude Code's
self-settings consent gate. A checkout still carrying a legacy
`config.yaml` is folded into `friction.yaml` by
`dev10x permission migrate-config` (GH-818), not by this skill.

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Seed session config", activeForm="Seeding session config")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Usage

Seed the current project (no-op for whichever file already exists):

```bash
uvx dev10x session seed
```

Options:

- `--path <dir>` — project root for the `.gitignore` (defaults to CWD).
- `--friction-level strict|guided|adaptive` — level written into a
  **fresh** `friction.yaml` `defaults` block (default `guided`).
  Ignored when `friction.yaml` already exists.

## Idempotency

The CLI uses an `O_EXCL` create per file, so anything already present is
left untouched and the command reports which path it skipped. Callers
may invoke this unconditionally.

## When to Use

- `Dev10x:work-on` Phase 0, when no gate policy resolves for this
  checkout and a default is needed before the first gate.
- After a `git worktree add` where the `post-checkout` hook was not
  installed (so the hook's own seed never ran).

Do NOT use this to change an existing policy — it only ever creates
missing files, and `--friction-level` is ignored once `friction.yaml`
exists. To change the posture, use `Dev10x:friction-setup` (durable,
per-project) or `Dev10x:afk` (walk-away), both of which write through
`dev10x session pin` / `set-friction`.
