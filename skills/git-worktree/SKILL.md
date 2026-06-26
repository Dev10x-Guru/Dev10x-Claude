---
name: Dev10x:git-worktree
description: >
  Create git worktrees for clean workspace isolation.
  Offers two modes: native EnterWorktree (switches CWD in current session)
  or external worktree (IDE-isolated, requires restarting claude in new dir).
  TRIGGER when: starting feature work needing isolation, or executing
  implementation plans with independent tasks.
  DO NOT TRIGGER when: work can be done on the current branch without
  isolation, or user explicitly wants to stay in the current worktree.
user-invocable: true
invocation-name: Dev10x:git-worktree
allowed-tools:
  - mcp__plugin_Dev10x_cli__next_worktree_name
  - mcp__plugin_Dev10x_cli__create_worktree
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/git-worktree/scripts/:*)
  - Bash(git worktree list:*)
  - Bash(git worktree remove:*)
---

# Git Worktree

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Create a task at invocation, mark completed when done:

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Create git worktree", activeForm="Creating worktree")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

**Announce:** "Using Dev10x:git-worktree skill to create an isolated workspace."

## Workflow

### Step 1: Determine Branch Name

The branch name is needed by both paths. Follow project naming conventions:

- username: check `git branch -a` for the pattern used (e.g. `janusz`)
- slug: lowercase ticket title, hyphens, stop-words removed, max 3–4 words
- regular repo: `username/TICKET-ID/slug`
- worktree: `username/TICKET-ID/worktree-name/slug`
  (worktree name = basename of the worktree directory, e.g. `app-pos-7`)

### Step 2: Choose Worktree Mode

Present the two options with AskUserQuestion:

- **Same session** (Recommended) — native `EnterWorktree` tool switches CWD
  immediately; all subsequent git commands and skills (`commit`, `Dev10x:gh-pr-create`,
  `branch:groom`) work without flags; worktree lives inside `.claude/worktrees/`
  (excluded from hook copies and `.gitignore`)
- **External + new session** — worktree created at `../.worktrees/<project>-NN`
  outside the project; IDE won't cross-index sibling worktrees; requires closing
  this session and opening a new one in the worktree directory

Continue to **Path A** or **Path B** based on the choice.

---

## Path A — Same Session (EnterWorktree)

### Step A1: Check post-checkout Hook

Read `.git/hooks/post-checkout` (or `.husky/post-checkout`) if it exists.
If it handles worktree setup adequately (uv sync, yarn install, env copy),
skip to Step A2.

If missing or incomplete, detect project type and propose the appropriate
template from the **Hook Templates** section below. Present to the user for
approval before writing. The hook must always ensure `.claude` exists —
either by copying from the source repo or creating an empty scaffold.

**Session config seeding (GH-705).** `.claude/Dev10x/session.yaml` is
gitignored (so it never trips the clean-tree gates in `verify_pr_state`
/ `gh-pr-merge` / `create_pr`), which means `git worktree add` does not
carry it into a new worktree. Every template in the **Hook Templates**
section copies it as part of the `.claude/` copy and then seeds a
default via `dev10x session seed` when the source had none — both inside
a marker-guarded block:

```sh
# >>> Dev10x session-seed (GH-705) >>>
if [ ! -f .claude/Dev10x/session.yaml ]; then
    if command -v dev10x >/dev/null 2>&1; then
        dev10x session seed || true
    elif command -v uvx >/dev/null 2>&1; then
        uvx dev10x session seed || true
    fi
fi
# <<< Dev10x session-seed (GH-705) <<<
```

**When the project already has an adequate post-checkout hook**, do NOT
overwrite it — **augment it idempotently**: read the hook, and only if
the `Dev10x session-seed (GH-705)` marker is absent, inject the block
above just before the hook's final cleanup/exit (inside the all-zeros
SHA guard if one exists). A hook that already contains the marker is
left untouched, so re-running this skill never duplicates the block.

### Step A1b: Detect Husky Version and Bootstrap ~/.huskyrc

When the project uses Husky, detect the version before creating
the worktree:

- **Husky v4**: `package.json` contains `"husky": { "hooks": ... }`
- **Husky v5+**: `.husky/_/husky.sh` exists

For **Husky v4** projects, worktrees lack `node_modules` until
`yarn install` completes, causing git hooks to fail. Check
`~/.huskyrc` and create it if missing:

```sh
# ~/.huskyrc — bootstrap for Husky v4 in worktrees
if [ ! -d "node_modules" ]; then
    echo "huskyrc: node_modules missing, skipping husky hook"
    exit 0
fi
```

For **Husky v5+** projects, no `~/.huskyrc` is needed.

**After writing any hook file**, always set executable permissions:
```sh
chmod +x .husky/post-checkout   # or .git/hooks/post-checkout
```

### Step A2: Create Worktree (native tool)

Call the native `EnterWorktree` tool:
- `name`: use the branch slug (e.g. `fix-railway-deployment`)

After `EnterWorktree` runs the session CWD is the new worktree. All
subsequent Bash calls, git commands, and skills operate inside it.

### Step A3: Continue Workflow

The session is now in the worktree. Resume the calling skill's next step
(ticket status, job story, summary). No restart needed.

**CWD & push discipline (GH-474 #6):** Although the session CWD is the
worktree, prefer **absolute paths** in Bash calls — a `cd X` in one call
does not persist to the next, so `cd subdir; <relative-path>` patterns
break when the CWD resets between calls. For pushing, raw `git push` is
hook-blocked on this worktree; use `Skill(Dev10x:git)` (which wraps
`push_safe`) instead of `git push` directly.

---

## Path B — External + New Session

### Step B1: Determine Worktree Location

Default pattern: `../.worktrees/<project-basename>-NN`

Calculate the next available path:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/git-worktree/scripts/next-worktree-name.sh
```

Ask user to confirm (AskUserQuestion):
- **Create at `<calculated-path>`** (Recommended)
- **Custom location** — let user specify

### Step B2: Check post-checkout Hook

Same as Step A1 — read, verify, and propose a template if needed.
See **Hook Templates** section below.

### Step B3: Create the Worktree

```bash
${CLAUDE_PLUGIN_ROOT}/skills/git-worktree/scripts/create-worktree.sh \
  <worktree-path> <branch-name> [repo-root]
```

- Omit `repo-root` when already inside the target repo.
- Pass `repo-root` when the CWD differs from the target repo.

The `post-checkout` hook fires automatically after this script runs.

### Step B4: Install SessionEnd Cleanup Hook

```bash
${CLAUDE_PLUGIN_ROOT}/skills/git-worktree/scripts/setup-session-end-hook.sh <worktree-path>
```

This writes a SessionEnd hook into `<worktree-path>/.claude/settings.local.json`
that prompts the user to remove the worktree when the new session ends.

### Step B5: Hand Off — STOP HERE

Claude Code sessions have a fixed CWD. `cd` inside a Bash call does not
persist, so every subsequent git command would need `git -C <path>` and
skills like `Dev10x:gh-pr-create` (whose `verify-state.sh` runs plain `git`) would fail.

Print this message and **stop — do not continue with ticket workflow steps**:

```
✅ Worktree ready
   Path:   <worktree-path>
   Branch: <branch-name>

Close this session and open a new one in the worktree:

  cd <worktree-path> && claude

Copy the command above, close this session, then paste it in your terminal.
The new session will have the correct CWD and all skills will work normally.
```

---

## Hook Templates

Templates for projects that lack a `post-checkout` hook.

### All hooks: use the all-zeros SHA guard

`git worktree add` passes `0000000000000000000000000000000000000000` as `$1`
(previous HEAD) when creating a new worktree. Guard on this value — do NOT
use `[ -f .git ]` which fires on every branch checkout inside any worktree:

```sh
if [ "$1" = "0000000000000000000000000000000000000000" ]; then
    # new worktree — run setup
fi
```

### Detect project type

| Check | Template |
|---|---|
| `uv.lock` or `pyproject.toml` exists | Template A (Python/uv) |
| `package.json` + `.husky/` directory | Template B (Node + Husky) |
| `package.json` without Husky | Template C (Node, no Husky) |

A project can match multiple templates (e.g. Django + SvelteKit). Apply all.

### Hook file location

| Condition | Write to |
|---|---|
| Husky present (`prepare` script or `.husky/` dir) | `.husky/post-checkout` (tracked) |
| No Husky | `.git/hooks/post-checkout` (untracked, local only) |

Husky overwrites `.git/hooks/` on every `yarn/npm install`. Writing to
`.git/hooks/post-checkout` in a Husky project means changes are silently lost.

### Template A: Python/uv

Source: [`templates/post-checkout-python-uv.sh`](./templates/post-checkout-python-uv.sh)

Copies `.env`, `development.secrets.env`, `.claude/` (excluding WIP), `.idea/`,
and runs `uv sync`.

**After creating a Python/uv worktree**, run `Dev10x:ide-normalize` to fix
stale PyCharm `.idea/` module-name references, disable
`ADD_CONTENT_ROOTS` / `ADD_SOURCE_ROOTS` flags (which conflict with editable
installs — see [PEP 660 / PYTHONPATH conflict](../ide-normalize/references/pep660-pythonpath-conflict.md)),
and detect the PyCharm uv-SDK `FLAVOR_DATA` gap that causes `ModuleNotFoundError`
on first launch.

### Template B: Node.js + Husky (write to `.husky/post-checkout`)

Source: [`templates/post-checkout-node-husky.sh`](./templates/post-checkout-node-husky.sh)

Copies `.env`, `.claude/` (excluding WIP), and runs `yarn install --frozen-lockfile`.

For monorepos (yarn workspaces), run `yarn install --frozen-lockfile` from
the repo root — this installs all workspace packages in one pass.

### Template C: Node.js without Husky (write to `.git/hooks/post-checkout`)

Source: [`templates/post-checkout-node.sh`](./templates/post-checkout-node.sh)

Copies `.env`, `.claude/` (excluding WIP), and runs `yarn install` or `npm ci`.

Make executable: `chmod +x .git/hooks/post-checkout`

**Never symlink `node_modules`** — a symlink means `yarn add/remove` in any
worktree mutates the shared directory. Always run `yarn install --frozen-lockfile`
(fast via Yarn's hardlink cache).

---

## Cleanup

The SessionEnd hook installed by Path B prompts:

> This session used worktree at `<path>`. Remove it? [y/N]

If yes: `git worktree remove <path>`
If no: the worktree persists for future sessions.

Manual removal:

```bash
git worktree remove <path>
git worktree remove --force <path>  # if dirty
git worktree list                   # list all worktrees
```

## Troubleshooting

### EnterWorktree Failure Recovery

If `EnterWorktree` fails (e.g., due to a hook error), it may leave
a partial worktree and orphan branch. Clean up manually:

```bash
git worktree remove <worktree-path> --force
git branch -D <worktree-branch>
```

Common failure causes:
- Husky v4 hooks require `node_modules` (see Step A1b)
- Yarn Berry needs `--immutable` not `--frozen-lockfile`
- Hook file not executable (ensure `chmod +x` after writing)

### PyCharm Crashes After Opening a New Worktree

**Symptom**: `uv run /full/path/.venv/bin/python manage.py …` crashes with
`ModuleNotFoundError: No module named 'collections.abc'`.

**Causes** (may be compounding):

1. **PyCharm uv-SDK FLAVOR_DATA gap** — PyCharm auto-creates an SDK entry
   with empty `FLAVOR_DATA="{}"`, missing `UV_VENV_PATH` / `UV_TOOL_PATH`.
   Result: PyCharm constructs the wrong launch command. Fix: run
   `Dev10x:ide-normalize` (Step 5) or follow the manual recipe in
   [`../ide-normalize/references/pycharm-uv-sdk-gap.md`](../ide-normalize/references/pycharm-uv-sdk-gap.md).

2. **ADD_CONTENT_ROOTS / ADD_SOURCE_ROOTS injecting PYTHONPATH** — These
   run-config defaults activate `sitecustomize` bootstrappers (New Relic,
   DataDog APM, etc.) that crash under uv-managed Python. Fix: run
   `Dev10x:ide-normalize` (Step 3) to set both flags to `false`.
   Background: [`../ide-normalize/references/pep660-pythonpath-conflict.md`](../ide-normalize/references/pep660-pythonpath-conflict.md).

**Quick fix**: `Dev10x:ide-normalize` addresses both causes.
