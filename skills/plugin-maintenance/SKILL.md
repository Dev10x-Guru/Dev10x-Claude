---
name: Dev10x:plugin-maintenance
description: >
  Maintain Dev10x plugin configuration — ensure base permissions,
  migrate config files, generalize session-specific allow rules,
  enumerate MCP tool globs, refresh script coverage, merge worktree
  permissions, audit permissions for friction, and clean redundant
  rules from project settings. Two modes: `bootstrap` (fast subset
  for first-time setup) and `full` (complete cleanup, default).
  TRIGGER when: bootstrapping a new install, after `claude plugin
  update`, when permission prompts appear unexpectedly, or when
  `Dev10x:onboarding` / `Dev10x:upgrade-cleanup` orchestrates
  maintenance.
  DO NOT TRIGGER when: permissions are already working and no
  upgrade or bootstrap is in progress.
user-invocable: true
invocation-name: Dev10x:plugin-maintenance
allowed-tools:
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/upgrade-cleanup/scripts/:*)
  - mcp__plugin_Dev10x_cli__update_paths
  - Agent(Dev10x:permission-auditor)
  - AskUserQuestion
  - TaskCreate
  - TaskUpdate
---

# Dev10x:plugin-maintenance

Single source for Dev10x plugin maintenance. Used directly, or
orchestrated by `Dev10x:onboarding` (bootstrap mode) and
`Dev10x:upgrade-cleanup` (full mode).

**Announce:** "Using plugin-maintenance to keep Dev10x permission
settings and config files in shape."

## Modes

| Mode | Steps | When to use |
|------|-------|-------------|
| `bootstrap` | 2, 3, 5 | First-time setup; eliminate prompts on the demoed skill set without doing a full sweep |
| `full` (default) | 1–8 | Post-upgrade; suspected permission friction; long-term maintenance |

`bootstrap` is intentionally fast and idempotent: ensure base
permissions, migrate any leftover legacy config files, and confirm
script coverage. It skips destructive cleanup (generalize, clean
project files) and the heavier `permission-auditor` sweep.

## Argument Parsing

Read the args string passed to the skill:

- empty / unset → mode = `full`
- starts with `bootstrap` → mode = `bootstrap`
- starts with `full` → mode = `full`
- anything else → mode = `full`, log a note that the arg was
  unrecognized

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
**Auto-advance:** complete each step, immediately start the next.
Run dry-run before applying — no pause between steps.

**REQUIRED: Create tasks before ANY work.** The task list depends
on the mode. Execute these `TaskCreate` calls at startup:

**Bootstrap mode:**

1. `TaskCreate(subject="Migrate config files", activeForm="Migrating configs")`
2. `TaskCreate(subject="Ensure workspace directories", activeForm="Registering workspace dirs")`
3. `TaskCreate(subject="Ensure base permissions", activeForm="Ensuring base perms")`
4. `TaskCreate(subject="Ensure script coverage", activeForm="Verifying script rules")`
5. `TaskCreate(subject="Ensure read coverage", activeForm="Verifying Read rules")`

**Full mode:**

1. `TaskCreate(subject="Update version paths", activeForm="Updating paths")`
2. `TaskCreate(subject="Migrate config files", activeForm="Migrating configs")`
3. `TaskCreate(subject="Ensure workspace directories", activeForm="Registering workspace dirs")`
4. `TaskCreate(subject="Ensure base permissions", activeForm="Ensuring base perms")`
5. `TaskCreate(subject="Generalize session-specific permissions", activeForm="Generalizing perms")`
6. `TaskCreate(subject="Enumerate MCP tool globs", activeForm="Enumerating MCP globs")`
7. `TaskCreate(subject="Ensure script coverage", activeForm="Verifying script rules")`
8. `TaskCreate(subject="Ensure read coverage", activeForm="Verifying Read rules")`
9. `TaskCreate(subject="Merge worktree permissions", activeForm="Merging worktree perms")`
10. `TaskCreate(subject="Audit permissions for friction", activeForm="Auditing permissions")`
11. `TaskCreate(subject="Clean project files", activeForm="Cleaning project files")`

Set sequential dependencies. Mark each step `in_progress` when
starting and `completed` when done. Steps that produce no
changes (dry-run shows no diff) should still be marked
`completed` with a note in the description.

## First-Time Setup

Initialize userspace config with your project roots:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/upgrade-cleanup/scripts/update-paths.py --init
```

Then edit `~/.claude/skills/Dev10x:upgrade-cleanup/projects.yaml`
to add your project roots. (The userspace config path keeps the
`upgrade-cleanup` directory name for backward compatibility — the
on-disk location does not change with the rename.)

## Workflow

The numbered headings below match the **full** mode task list.
In `bootstrap` mode, run only the steps marked **[bootstrap]**.

### 1. Update version paths *(full only)*

Bump versioned plugin paths in every settings file to the current
plugin version.

1. Dry run:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/upgrade-cleanup/scripts/update-paths.py --dry-run
```

For large updates prefer `--summary`:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/upgrade-cleanup/scripts/update-paths.py --dry-run --summary
```

2. Apply:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/upgrade-cleanup/scripts/update-paths.py
```

### 2. Migrate config files **[bootstrap]**

Move config files from deprecated locations to canonical Dev10x
paths. Files are moved (not copied) so old paths stop working
immediately.

| Old path | New path |
|----------|----------|
| `~/.claude/memory/slack-config.yaml` | `~/.claude/memory/Dev10x/slack-config.yaml` |
| `~/.claude/memory/slack-config-code-review-requests.yaml` | `~/.claude/memory/Dev10x/slack-config-code-review-requests.yaml` |
| `~/.claude/memory/github-reviewers-config.yaml` | `~/.claude/memory/Dev10x/github-reviewers-config.yaml` |
| `~/.claude/memory/databases.yaml` | `~/.claude/memory/Dev10x/databases.yaml` |

For each file:
1. Check if source exists (skip if not — user may not use it)
2. Check destination exists (skip + warn if both present)
3. Ensure `~/.claude/memory/Dev10x/` exists
4. `mv` source to destination
5. Report what moved

### 3. Ensure workspace directories **[bootstrap]** (GH-40)

Register paths outside the project root (e.g. `/tmp/Dev10x`) under
`permissions.additionalDirectories` in every settings file. Allow-rules
like `Write(/tmp/Dev10x/**)` are NOT sufficient — Claude Code requires
the directory to be registered as an additional working directory
or it prompts on every Write/Edit/Read until the user runs
`/permissions add /tmp/Dev10x` interactively.

Directories registered come from `workspace_directories:` in
`${CLAUDE_PLUGIN_ROOT}/skills/upgrade-cleanup/projects.yaml`.

```bash
mcp__plugin_Dev10x_cli__update_paths(ensure_workspace=true, dry_run=true)
mcp__plugin_Dev10x_cli__update_paths(ensure_workspace=true)
```

### 4. Ensure base permissions **[bootstrap]**

Add missing base permissions (gh CLI, /tmp/Dev10x paths, git ops,
MCP tools, Dev10x config file RWE access) to all settings files.
The base set is defined in
`${CLAUDE_PLUGIN_ROOT}/skills/upgrade-cleanup/projects.yaml`
under `base_permissions:`.

**Enumeration requirement:** All script paths and MCP tool names
MUST be listed individually in `base_permissions`. Glob wildcards
(e.g., `Bash(~/.claude/plugins/cache/**:*)` or
`mcp__plugin_Dev10x_*`) cause permission friction — Claude Code
cannot pre-approve glob patterns for Bash or MCP tools, so each
invocation triggers a manual approval prompt. When adding new
scripts or MCP tools to the plugin, enumerate them explicitly in
`projects.yaml` following the existing per-script and per-tool
entries.

1. Dry run:

```
mcp__plugin_Dev10x_cli__update_paths(ensure_base=true, dry_run=true)
```

2. Apply:

```
mcp__plugin_Dev10x_cli__update_paths(ensure_base=true)
```

### 5. Generalize session-specific permissions *(full only)*

Replace permission rules containing session-specific arguments
(ticket IDs, PR numbers, temp file hashes) with generalized
wildcard patterns that work across future sessions.

1. Dry run:

```
mcp__plugin_Dev10x_cli__update_paths(generalize=true, dry_run=true)
```

2. Apply:

```
mcp__plugin_Dev10x_cli__update_paths(generalize=true)
```

**What gets generalized:**
- `detect-tracker.sh PAY-123` → `detect-tracker.sh *`
- `gh-pr-detect.sh 42` → `gh-pr-detect.sh *`
- `gh-issue-get.sh 15` → `gh-issue-get.sh *`
- `generate-commit-list.sh 42` → `generate-commit-list.sh *`
- `/tmp/Dev10x/git/msg.AbCdEf.txt` → `/tmp/Dev10x/git/**`

### 6. Enumerate MCP tool globs *(full only)*

Claude Code does not expand `mcp__plugin_Dev10x_*` globs in allow
rules — glob-shaped MCP rules match nothing. This step discovers
Dev10x MCP tools and replaces any matching wildcard with the
enumerated tool list.

> **Note:** With `ensure_base` already auto-expanding stale MCP
> wildcards in step 3 (since v0.66.0), this step is usually a
> no-op. Run it to catch wildcards introduced by external edits.

1. Dry run:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/upgrade-cleanup/scripts/enumerate-mcp.py --dry-run
```

2. Apply:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/upgrade-cleanup/scripts/enumerate-mcp.py
```

### 7. Ensure script coverage **[bootstrap]**

Verify that all callable scripts in the current plugin version
have individual allow rules in each settings file. New plugin
versions may add scripts that are not yet enumerated.

1. Dry run:

```
mcp__plugin_Dev10x_cli__update_paths(ensure_scripts=true, dry_run=true)
```

2. Add missing rules:

```
mcp__plugin_Dev10x_cli__update_paths(ensure_scripts=true)
```

**What gets scanned:**
- `bin/*.sh` — helper scripts
- `hooks/scripts/*.py`, `hooks/scripts/*.sh` — hook implementations
- `skills/*/scripts/*.py`, `skills/*/scripts/*.sh` — skill scripts

### 8. Ensure read coverage **[bootstrap]**

Verify that every skill folder and recognized top-level plugin
directory has a per-folder `Read(...)` allow rule. Empirical
evidence shows the engine matches rule strings literally against
the prompt-displayed path, so each rule ships in two variants —
`Read(~/...)` and `Read(/home/<user>/...)` — and uses a single
`*` wildcard rather than `*/**` (GH-47).

> **Why both variants:** The permission engine does not normalize
> `~/` and `/home/<user>/`, so emitting both shapes is the
> belt-and-suspenders fix until the engine learns to.

1. Dry run:

```
mcp__plugin_Dev10x_cli__update_paths(ensure_reads=true, dry_run=true)
```

2. Apply:

```
mcp__plugin_Dev10x_cli__update_paths(ensure_reads=true)
```

**What gets emitted (per skill, per top-level dir):**
- `Read(~/.claude/plugins/cache/<pub>/<plugin>/<version>/skills/<name>/*)`
- `Read(/home/<user>/.claude/plugins/cache/<pub>/<plugin>/<version>/skills/<name>/*)`

The version segment is shared with `update-paths`, so both
variants update in lockstep on plugin upgrade.

### 9. Merge worktree permissions *(full only)*

Worktrees accumulate allow rules during sessions that the main
project never sees. This script collects stable permissions from
all worktrees and merges them back.

1. Dry run:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/upgrade-cleanup/scripts/merge-worktree-permissions.py --dry-run
```

2. Apply:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/upgrade-cleanup/scripts/merge-worktree-permissions.py
```

Session-specific noise is filtered out automatically; only
stable, reusable permissions are merged.

### 10. Audit permissions for friction *(full only)*

Dispatch the `permission-auditor` agent to perform a comprehensive
7-phase security and friction audit. The agent analyzes:

- Overly broad allow rules that should be narrowed
- Script-call permissions that should use skills instead
- Missing deny rules for destructive operations
- Dead rules blocked by hooks
- Hardcoded paths in instruction files

**Invoke:**

```
Agent(subagent_type="Dev10x:permission-auditor",
    description="Audit permission settings",
    prompt="Audit all Claude Code permission settings for security
    gaps, overly broad rules, and friction-causing patterns.
    Pay special attention to allow rules that permit direct script
    calls when equivalent skills exist — these cause friction and
    should be replaced with Skill() invocations or blocked.")
```

The agent produces a severity-categorized report with specific
fix proposals. Review and apply selectively.

### 11. Clean project files *(full only)*

Strip redundant rules from project `settings.local.json` files
that are now covered by global `~/.claude/settings.json`. Also
flags rules containing leaked secrets.

1. Dry run:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/upgrade-cleanup/scripts/clean-project-files.py --dry-run
```

For large cleanups prefer `--summary`:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/upgrade-cleanup/scripts/clean-project-files.py --dry-run --summary
```

2. Apply:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/upgrade-cleanup/scripts/clean-project-files.py
```

**What gets cleaned:**
- Exact duplicates of global rules
- Rules covered by global wildcard patterns
- Old plugin version paths (any version older than current)
- Env-prefixed session noise (`GIT_SEQUENCE_EDITOR=*`, …)
- Shell control flow fragments (`do`, `done`, `fi`, …)
- Double-slash path typos (`Read(//work/...)`)

**Leaked secret detection:** Rules containing plaintext
credentials are flagged with warnings so users can rotate them.

## Configuration

The script looks for `projects.yaml` in two locations (first wins):
1. `~/.claude/skills/Dev10x:upgrade-cleanup/projects.yaml` (userspace)
2. `${CLAUDE_PLUGIN_ROOT}/skills/upgrade-cleanup/projects.yaml` (plugin default)

The userspace location is preserved across the rename so existing
users do not need to migrate config files.

## Options

### update_paths MCP tool

| Parameter | Purpose |
|-----------|---------|
| `dry_run` | Preview changes without writing |
| `version` | Target a specific version instead of latest |
| `init` | Copy plugin default config to userspace for customization |
| `ensure_base` | Add missing base permissions from projects.yaml |
| `generalize` | Replace session-specific args with wildcard patterns |
| `ensure_scripts` | Verify all plugin scripts have allow rules; add missing |
| `ensure_reads` | Emit per-skill folder Read rules with `~/` + `/home/<user>/` twins |

### update-paths.py CLI

| Flag | Purpose |
|------|---------|
| `--dry-run` | Preview what would change without writing |
| `--summary` | One line per changed file |
| `--quiet` | Suppress per-file details and headers |
| `--version VER` | Target a specific version |
| `--restore` | Restore settings from most recent backups |

### merge-worktree-permissions.py / clean-project-files.py

Both accept `--dry-run` (and `--summary` for clean-project-files).
See the script `--help` output for the full list.
