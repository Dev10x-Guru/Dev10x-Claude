---
name: dev10x:git-worktree-prune
description: >
  Use when worktree checkouts of merged work have piled up — so the safe
  ones are removed behind one approval, without a 70-call manual sweep
  and without losing a dirty, unpushed or in-use checkout.
  TRIGGER when: `git worktree list` has grown long after fanout, crew or
  herdr sessions, or someone asks to clean up merged worktrees.
  DO NOT TRIGGER when: removing local branches (use
  dev10x:git-branch-prune), or removing the one worktree a session just
  finished with (the git-worktree SessionEnd prompt covers it).
user-invocable: true
invocation-name: dev10x:git-worktree-prune
allowed-tools:
  - AskUserQuestion
  - mcp__plugin_dev10x_cli__detect_base_branch
  - mcp__plugin_dev10x_cli__worktree_prune_candidates
  - Bash(git fetch --prune:*)
  - Bash(git worktree remove:*)
  - Bash(git worktree prune:*)
---

# dev10x:git-worktree-prune

**Announce:** "Using dev10x:git-worktree-prune to classify worktrees and
remove the ones whose work has already merged."

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Prune merged worktrees", activeForm="Pruning worktrees")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

**Leave an open task (GH-149).** Before completing it, check `TaskList`.
When no `Verify AC` task exists and the list would otherwise be empty,
create one first — `TaskCreate(subject="Verify AC and close session",
description="<removed, skipped and kept paths>", activeForm="Verifying
AC")` — and never complete it yourself
(`.claude/rules/essentials.md` § Task List Invariant).

## Overview

`dev10x:git-worktree` only creates checkouts, and `git worktree prune`
drops admin entries for paths that are already gone. Nothing removes a
live checkout whose branch merged, so they accumulate. A hand sweep is
slow and gets the hard cases wrong:

- **Squash merges** — ancestry checks and `[gone]` upstreams miss them;
  merge state comes from the PR.
- **Generated mirrors** — untracked `.agents/` / `.codex/` make
  `git worktree remove` refuse without `--force`.
- **Stale reads** — a status read during the survey can be wrong by the
  time of removal.
- **Live workspaces** — herdr reports an `open_workspace_id` for a
  checkout in use.
- **New worktrees mid-run** — a parallel session can add checkouts while
  this one runs.
- **Merged but dirty** — a merged branch does not make the checkout
  disposable.

The `worktree_prune_candidates` MCP tool settles all of these in one
read-only call; this skill turns its answer into one approval and a
careful removal loop.

## Workflow

### Step 1: Survey

1. Call `mcp__plugin_dev10x_cli__detect_base_branch` and use its
   `base_branch` throughout — never hardcode `develop`.
2. Run `git fetch --prune origin` so the unpushed-commit count and the
   base ref are current.
3. Call `mcp__plugin_dev10x_cli__worktree_prune_candidates(base=<base>,
   cwd=<absolute path of this checkout>)`. Always pass `cwd` — the MCP
   server is long-lived and its own directory may be another repo or a
   removed worktree. Branch on an `error` key: report it and stop.
4. Record the **surveyed set** — every `path` in `worktrees` with its
   `branch` and `head`. Steps 3 and 4 act only on paths in this set.

The tool groups every worktree:

| Class | Meaning |
|-------|---------|
| `remove` | Clean or mirrors-only, nothing on no remote, not open in herdr, merged PR (head matches, or HEAD is on base) |
| `ask` | Clean and pushed, but its PR closed unmerged, or it has no PR |
| `keep` | Main or current checkout, dirty, holding ignored files outside known caches, unpushed, open, locked, open PR, moved past its merged PR, missing, or any state it could not read |

Ignored files (a local `.env`, settings) are deleted by `git worktree
remove` even without `--force`, so any `ignored_paths` entry keeps the
checkout. Only `.venv/`, `node_modules/`, `__pycache__/`,
`.pytest_cache/`, `.ruff_cache/` and `.mypy_cache/` are disregarded.

The response's `herdr` field says how open workspaces were read. When
herdr is not on the server's PATH but `~/.herdr` exists or `HERDR_ENV`
is set, the state is unknown and every otherwise-removable checkout is
kept. Herdr items lacking `path` or `open_workspace_id` are unknown too.

### Step 2: Approval gate

When `remove` and `ask` are both empty, print the `keep` table and skip
to Step 4.

Otherwise present, before the question:

- `remove` and `ask` paths with branch, PR, `last_commit_at` and
  `reason`, as code blocks;
- the `keep` paths with their `reason`, so nothing is hidden;
- the survey's `herdr` value as a line `herdr: <value>`, so a missing
  herdr (`herdr: absent`) is visible instead of reading as "nothing open".

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text). This blocks
every removal until the user answers. Options — mark exactly one
`(Recommended)` and list it first, computed from the survey: "Remove
safe" leads when `remove` is non-empty, "Remove nothing" leads when it
is empty:

- **Remove safe** — remove only the `remove` set
- **Remove safe + ask** — also remove every `ask` path
- **Remove nothing** — report only

The user may answer "Other" with an explicit path list; accept only
paths from the surveyed set and drop anything else with a note.

### Step 3: Remove, re-reading each path first

For each approved path, one at a time:

1. Call `mcp__plugin_dev10x_cli__worktree_prune_candidates(base=<base>,
   paths=[<path>], cwd=<same checkout as Step 1>)` — a fresh read,
   never the survey's.
2. Remove it only when **all** of these hold — otherwise skip it and
   report the fresh `reason` (or the error):
   - the response has no `error` key and the path is not in `not_found`;
   - the path appears in the response's `worktrees` list — read its
     fresh `class` and `force_required` from that entry;
   - its fresh `branch` and `head` equal the surveyed ones — a path
     removed and recreated by a parallel session is a different
     checkout, so skip it on any difference;
   - that `class` is one the answer approved: `remove` for **Remove
     safe**; `remove` or `ask` for **Remove safe + ask** or an explicit
     "Other" path list.

   So under **Remove safe** a path whose class drifted from `remove` to
   `ask` (its PR closed after the survey) is skipped, and a fresh `keep`
   is skipped under every answer.
3. Remove it:
   - `force_required: false` → `git worktree remove <path>`
   - `force_required: true` → `git worktree remove --force <path>`.
     The tool sets this only when the untracked set is a subset of the
     generated mirrors and nothing else is dirty.
4. Record a failure and continue with the next path — one refusal must
   not abort the batch.

### Step 4: Finish

1. Run `git worktree prune` to clear admin entries of missing paths.
2. Report removed, skipped (with the fresh reason) and kept paths.
3. Point to branch cleanup: "Local branches are untouched — run
   `dev10x:git-branch-prune` to remove merged ones."

## Permissions

`git worktree remove` and `git worktree prune` stay out of every
`base_permissions` catalog on purpose: they delete files, so each call
prompts (GH-1942, supervisor decision). Do not seed them.

## Anti-Patterns

- Never delete a branch — `dev10x:git-branch-prune` owns that.
- Never pass `--force` unless the fresh read says `force_required: true`.
- Never act on a survey result without the Step 3 re-read.
- Never touch a worktree that appeared after the survey.
- Never treat "branch merged" as "checkout disposable" — `keep` wins.
