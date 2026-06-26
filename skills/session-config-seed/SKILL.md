---
name: Dev10x:session-config-seed
description: >
  Seed a default .claude/Dev10x/session.yaml when it is missing, so
  work-on / verify-acc-dod have a session config to read. Idempotent —
  an existing file is preserved. TRIGGER when: a skill (e.g. work-on
  Phase 0) finds session.yaml absent and needs a default before
  reading friction_level / active_modes. DO NOT TRIGGER when:
  session.yaml already exists (the seed is a no-op), or you need to
  CHANGE an existing config (edit it directly — this skill never
  overwrites).
user-invocable: true
invocation-name: Dev10x:session-config-seed
allowed-tools:
  - Bash(uvx dev10x session seed:*)
  - Bash(dev10x session seed:*)
---

**Announce:** "Using Dev10x:session-config-seed to seed session config."

# Dev10x:session-config-seed — Seed session.yaml when missing

Thin wrapper over `dev10x session seed`. The CLI does an idempotent
`O_EXCL` write of a default `.claude/Dev10x/session.yaml` — so this
skill is the agent-time counterpart to the shell-only `post-checkout`
hook (a git hook cannot invoke a Claude skill, GH-705). Both call the
same CLI, so seeding behaves identically whether triggered at worktree
creation (hook) or at session start (this skill).

`session.yaml` is gitignored (it must never enter a feature PR — that
is what trips the clean-tree gates in `verify_pr_state` /
`Dev10x:gh-pr-merge` / `create_pr`), which is exactly why it needs an
explicit seed: a gitignored file does not follow `git worktree add`.

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Seed session config", activeForm="Seeding session config")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Usage

Seed the current project (no-op if `session.yaml` already exists):

```bash
uvx dev10x session seed
```

Options:

- `--path <dir>` — seed a different project root (defaults to CWD).
- `--friction-level strict|guided|adaptive` — level written only when
  the file is absent (default `guided`).

## Idempotency

The CLI uses an `O_EXCL` create, so an existing `session.yaml` — for
example one the `post-checkout` hook copied from the source worktree —
is left untouched. Callers may invoke this unconditionally.

## When to Use

- `Dev10x:work-on` Phase 0, when `session.yaml` is missing and the
  friction level / active modes must be read.
- After a `git worktree add` where the `post-checkout` hook was not
  installed (so the hook's own seed never ran).

Do NOT use this to change an existing config — it only ever creates a
missing file. To change friction level or active modes, edit
`session.yaml` directly or re-run `dev10x init --setup`.
