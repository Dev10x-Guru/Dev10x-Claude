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
  # GH-269: Plugin maintenance now runs through the version-stable
  # `uvx dev10x` CLI. Each subcommand is enumerated explicitly (no
  # `Bash(uvx dev10x:*)` wildcard) for user trust and transparency —
  # the maintainer can audit exactly which subcommands this skill is
  # authorized to invoke.
  - Bash(uvx dev10x permission update-paths:*)
  - Bash(uvx dev10x permission merge-worktree:*)
  - Bash(uvx dev10x permission clean:*)
  - Bash(uvx dev10x permission enumerate-mcp:*)
  - Bash(uvx dev10x permission ensure-base:*)
  - Bash(uvx dev10x permission ensure-reads:*)
  - Bash(uvx dev10x permission ensure-scripts:*)
  - Bash(uvx dev10x permission ensure-workspace:*)
  - Bash(uvx dev10x permission generalize:*)
  - Bash(uvx dev10x permission doctor:*)
  - Bash(uvx dev10x permission doctor anchor-worktree-roots:*)
  - Bash(uvx dev10x permission init:*)
  - Bash(uvx dev10x permission investigate:*)
  - Bash(uvx dev10x permission record-upgrade:*)
  - Bash(uvx dev10x playbook diff:*)
  # GH-307: version-check preflight
  - Bash(claude plugin list:*)
  - Bash(uv tool list:*)
  - Read(~/.config/Dev10x/*)
  - Write(~/.config/Dev10x/*)
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
| `bootstrap` | version-check, 2, 3, 5 | First-time setup; eliminate prompts on the demoed skill set without doing a full sweep |
| `full` (default) | version-check, 1–8 | Post-upgrade; suspected permission friction; long-term maintenance |

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
**Auto-advance:** complete each step, immediately start the next — no checkpoints under adaptive friction.
Run dry-run before applying — no pause between steps.

**REQUIRED: Create tasks before ANY work.** The task list depends
on the mode. Execute these `TaskCreate` calls at startup:

**Bootstrap mode:**

1. `TaskCreate(subject="Check for newer version (plugin + uv tool)", activeForm="Checking versions")`
2. `TaskCreate(subject="Migrate config files", activeForm="Migrating configs")`
3. `TaskCreate(subject="Ensure workspace directories", activeForm="Registering workspace dirs")`
4. `TaskCreate(subject="Ensure base permissions", activeForm="Ensuring base perms")`
5. `TaskCreate(subject="Ensure script coverage", activeForm="Verifying script rules")`
6. `TaskCreate(subject="Ensure read coverage", activeForm="Verifying Read rules")`

**Full mode:**

1. `TaskCreate(subject="Check for newer version (plugin + uv tool)", activeForm="Checking versions")`
2. `TaskCreate(subject="Update version paths", activeForm="Updating paths")`
3. `TaskCreate(subject="Migrate config files", activeForm="Migrating configs")`
4. `TaskCreate(subject="Ensure workspace directories", activeForm="Registering workspace dirs")`
5. `TaskCreate(subject="Ensure base permissions", activeForm="Ensuring base perms")`
6. `TaskCreate(subject="Generalize session-specific permissions", activeForm="Generalizing perms")`
7. `TaskCreate(subject="Enumerate MCP tool globs", activeForm="Enumerating MCP globs")`
8. `TaskCreate(subject="Ensure script coverage", activeForm="Verifying script rules")`
9. `TaskCreate(subject="Ensure read coverage", activeForm="Verifying Read rules")`
10. `TaskCreate(subject="Merge worktree permissions", activeForm="Merging worktree perms")`
11. `TaskCreate(subject="Audit permissions for friction", activeForm="Auditing permissions")`
12. `TaskCreate(subject="Clean project files", activeForm="Cleaning project files")`
13. `TaskCreate(subject="Run permission doctor", activeForm="Running doctor sweep")`
14. `TaskCreate(subject="Diff user playbooks against defaults", activeForm="Diffing playbooks")`

Set sequential dependencies. Mark each step `in_progress` when
starting and `completed` when done. Steps that produce no
changes (dry-run shows no diff) should still be marked
`completed` with a note in the description.

## Preflight: check for newer version (GH-307)

Before any maintenance work, report installed vs latest for both
the Claude Code plugin and the `dev10x` uv tool, and offer to
update when either is behind.

### Step 1: Read the preference file

Try to load the saved update preference from
`~/.config/Dev10x/plugin-maintenance-prefs.yaml`:

```yaml
# example
update_preference: both   # both | plugin | uv | skip | ask
```

If the file exists and `update_preference` is set to anything
other than `ask`, use that value to auto-skip the first
`AskUserQuestion` gate (still show the version report, just
apply the saved choice). If the file is absent or
`update_preference: ask`, present the gate normally.

### Step 2: Read latest advertised version

Read the `version` field from the marketplace manifest:

```
~/.claude/plugins/marketplaces/<publisher>/<plugin>/.claude-plugin/plugin.json
```

Locate the manifest by globbing
`~/.claude/plugins/marketplaces/*/*/.claude-plugin/plugin.json`
and filtering for the Dev10x plugin (check the `name` field).
Parse `version` as the "latest advertised" version.

If the manifest is not found, skip the plugin version check and
note "marketplace manifest not found".

### Step 3: Read installed plugin version

Run:

```bash
claude plugin list
```

Parse the output for the Dev10x plugin entry. Extract both the
installed version **and the install scope** (`local` or `user` —
the scope is required for the correct `claude plugin update`
invocation). If the entry is absent, note "plugin not installed".

### Step 4: Read uv tool version

Run:

```bash
uv tool list
```

Parse the output for the `dev10x` entry and extract its version.
If absent, note "uv tool not installed".

### Step 5: Display version report

Always display a concise version report before prompting:

```
Version check
  Plugin (marketplace latest): 0.75.0
  Plugin (installed):          0.74.0  ← behind
  uv tool dev10x:              0.73.0  ← behind
```

If both are current, display the table with "✓ up to date" and
skip to the next maintenance step — no prompt needed.

### Step 6: Prompt to update (when behind)

If either surface is behind, **REQUIRED: Call `AskUserQuestion`**
(do NOT use plain text). Apply the saved preference from Step 1
instead of prompting when `update_preference` is set.

```
AskUserQuestion(questions=[{
  question: "One or more Dev10x surfaces are behind the latest version.\nHow would you like to proceed?",
  header: "Version update",
  options: [
    {label: "Update both (Recommended)",
     description: "claude plugin update + uv tool upgrade dev10x"},
    {label: "Plugin only",
     description: "claude plugin update <plugin>@<marketplace>"},
    {label: "uv tool only",
     description: "uv tool upgrade dev10x"},
    {label: "Skip",
     description: "Continue maintenance without updating"}
  ],
  multiSelect: false
}])
```

**Execute the chosen update(s):**

- **Plugin update:** Run `claude plugin update` using the scope
  detected in Step 3 (e.g., `claude plugin update Dev10x@Dev10x-Guru`
  for user-scoped installs, or with `--local` for local-scoped).
  After a successful plugin update, surface this hint:
  > **Restart required** — the running Claude session keeps the
  > cached skill content until restart. Reload Claude Code to load
  > the new plugin version.

- **uv tool update:** Run `uv tool upgrade dev10x`.

### Step 7: Remember the decision

After the user makes a choice in Step 6, **REQUIRED: Call
`AskUserQuestion`** (do NOT use plain text):

```
AskUserQuestion(questions=[{
  question: "Remember this choice for future maintenance sessions?",
  header: "Save preference",
  options: [
    {label: "Yes, remember for future sessions (Recommended)",
     description: "Saves preference to ~/.config/Dev10x/plugin-maintenance-prefs.yaml"},
    {label: "No, ask me each time",
     description: "Preference is not saved"}
  ],
  multiSelect: false
}])
```

If the user chooses to remember: write the chosen preference to
`~/.config/Dev10x/plugin-maintenance-prefs.yaml`:

```yaml
# Written by Dev10x:plugin-maintenance (GH-307)
# Valid values: both | plugin | uv | skip | ask
update_preference: <choice>
```

The `ask` value means "always prompt, never auto-apply" and is
the effective default when the file is absent.

---

## Preflight: ensure `uv` (and `uvx`) is installed (GH-269)

Every command in this skill runs through `uvx dev10x …`, the
version-stable CLI shipped with the plugin. If `uv` is missing,
none of the maintenance commands can run. Before any step:

```bash
command -v uvx
```

If the command prints nothing (exit status non-zero), STOP and
direct the user to install `uv` first:

> `uv` (which provides `uvx`) is not installed. Run the
> `Dev10x:onboarding` skill — it installs `uv` via the official
> Astral installer and verifies the plugin can drive its CLI.
> Direct install instructions: <https://docs.astral.sh/uv/getting-started/installation/>

Delegate via `Skill(Dev10x:onboarding)` and re-run this skill once
`uv` is on PATH.

## First-Time Setup

Initialize userspace config with your project roots:

```bash
uvx dev10x permission update-paths --init
```

Then edit `~/.claude/skills/Dev10x:upgrade-cleanup/projects.yaml`
to add your project roots. (The userspace config path keeps the
`upgrade-cleanup` directory name for backward compatibility — the
on-disk location does not change with the rename.)

## Workflow

The numbered headings below (1–13) match the **full** mode task
list steps 2–14 (after the version-check preflight).
In `bootstrap` mode, run only the steps marked **[bootstrap]**.

### 1. Update version paths *(full only)*

Bump versioned plugin paths in every settings file to the current
plugin version.

1. Dry run (REQUIRED — always show the user the planned changes
   before applying):

```bash
uvx dev10x permission update-paths --dry-run
```

For large updates prefer `--summary`:

```bash
uvx dev10x permission update-paths --dry-run --summary
```

2. Apply (only after the dry-run output is shared with the user):

```bash
uvx dev10x permission update-paths
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

1. Dry run (REQUIRED — show the user before applying):

```bash
uvx dev10x permission ensure-workspace --dry-run
```

2. Apply:

```bash
uvx dev10x permission ensure-workspace
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

```bash
uvx dev10x permission ensure-base --dry-run
```

2. Apply:

```bash
uvx dev10x permission ensure-base
```

### 5. Generalize session-specific permissions *(full only)*

Replace permission rules containing session-specific arguments
(ticket IDs, PR numbers, temp file hashes) with generalized
wildcard patterns that work across future sessions.

1. Dry run:

```bash
uvx dev10x permission generalize --dry-run
```

2. Apply:

```bash
uvx dev10x permission generalize
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

1. Dry run (REQUIRED — show the user before applying):

```bash
uvx dev10x permission enumerate-mcp --dry-run
```

2. Apply:

```bash
uvx dev10x permission enumerate-mcp
```

### 7. Ensure script coverage **[bootstrap]**

Verify that all callable scripts in the current plugin version
have individual allow rules in each settings file. New plugin
versions may add scripts that are not yet enumerated.

1. Dry run:

```bash
uvx dev10x permission ensure-scripts --dry-run
```

2. Add missing rules:

```bash
uvx dev10x permission ensure-scripts
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

```bash
uvx dev10x permission ensure-reads --dry-run
```

2. Apply:

```bash
uvx dev10x permission ensure-reads
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

1. Dry run (REQUIRED — show the user before applying):

```bash
uvx dev10x permission merge-worktree --dry-run
```

2. Apply:

```bash
uvx dev10x permission merge-worktree
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

1. Dry run (REQUIRED — show the user before applying):

```bash
uvx dev10x permission clean --dry-run
```

For large cleanups prefer `--summary`:

```bash
uvx dev10x permission clean --dry-run --summary
```

2. Apply:

```bash
uvx dev10x permission clean
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

### 12. Run permission doctor *(full only)* (GH-99)

Apply the baseline-permissions catalog and detect cross-project /
worktree↔source-repo contamination. The doctor handles three classes
of friction not covered by the other steps:

- **Pinned plugin paths** — version-rotted rules like
  `Bash(/home/u/.claude/plugins/cache/Dev10x-Guru/Dev10x/0.71.0/...)`
  are rewritten to the version-wildcard form
  `Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/**/...)` so they
  survive `claude plugin update`.
- **Catalog deprecations** — entries from
  `src/dev10x/skills/permission/baseline-permissions.yaml` with
  `action: canonicalize` are rewritten; `action: remove` entries
  (e.g., legacy `/tmp/claude/bin/mktmp.sh:*`) are dropped.
- **Cross-contamination** — rules whose absolute paths point outside
  the current project, or into the source repo when CWD is a worktree,
  are flagged so the user can remove them.

1. Canonicalize pinned paths (idempotent, safe to re-run):

```bash
uvx dev10x permission doctor canonicalize --dry-run
uvx dev10x permission doctor canonicalize
```

2. Apply catalog deprecations:

```bash
uvx dev10x permission doctor apply-deprecations --dry-run
uvx dev10x permission doctor apply-deprecations
```

3. Scan for cross-contamination (no auto-fix — surfaces findings only):

```bash
uvx dev10x permission doctor cross-contamination
```

4. Anchor `.worktrees` parent roots (GH-376) — ensures project-level
   `.worktrees` parents are registered in `additionalDirectories` and
   flags bare-relative skill-script allow rules:

```bash
uvx dev10x permission doctor anchor-worktree-roots --dry-run
uvx dev10x permission doctor anchor-worktree-roots
```

5. Enable an opt-in Tier 3 group when needed (e.g., `kubernetes-readonly`,
   `network-diagnostics`, `obsidian-cli`):

```bash
uvx dev10x permission doctor enable-group kubernetes-readonly --dry-run
uvx dev10x permission doctor enable-group kubernetes-readonly
```

### 13. Diff user playbooks against plugin defaults *(full only)* (GH-192)

User playbook overrides under `.claude/Dev10x/playbooks/` and
`~/.claude/memory/Dev10x/playbooks/` drift from the plugin defaults as
new versions ship new steps, fragments, or field changes. This step
surfaces those upstream changes without overwriting user customizations.

```bash
uvx dev10x playbook diff
```

The report distinguishes:

- **New** steps present in the plugin default but missing from the user
  override — typically upstream additions worth pulling in
- **Removed** steps or plays the user overrides that no longer exist in
  the default — either intentional pruning or upstream removal
- **Changed** steps where the user has not overridden a field whose
  default value moved upstream
- **Customized** fields the user has explicitly set — flagged as
  preserved; the diff never proposes overwriting them

To pull in upstream changes interactively, run:

```bash
/Dev10x:playbook edit <skill> <play>
```

To target one skill (skip the rest):

```bash
uvx dev10x playbook diff --skill work-on
```

## Configuration

The script looks for `projects.yaml` in two locations (first wins):
1. `~/.claude/skills/Dev10x:upgrade-cleanup/projects.yaml` (userspace)
2. `${CLAUDE_PLUGIN_ROOT}/skills/upgrade-cleanup/projects.yaml` (plugin default)

The userspace location is preserved across the rename so existing
users do not need to migrate config files.

## Options

All maintenance commands are subcommands of `uvx dev10x permission …`.
Run `uvx dev10x permission <subcommand> --help` for the authoritative
flag list.

### Common flags (most subcommands)

| Flag | Purpose |
|------|---------|
| `--dry-run` | Preview what would change without writing |
| `--summary` | One line per changed file (where supported) |
| `--quiet` | Suppress per-file details and headers |

### `update-paths` extras

| Flag | Purpose |
|------|---------|
| `--init` | Copy plugin default config to userspace for customization |
| `--version VER` | Target a specific version instead of latest |
| `--restore` | Restore settings from most recent backups |
