---
name: dev10x:upgrade-cleanup
description: >
  Post-upgrade cleanup entry point — delegates to
  `dev10x:plugin-maintenance` in `full` mode. Updates plugin
  version paths, ensures base permissions, migrates config files
  (including global playbook overrides from
  ~/.claude/memory/Dev10x/playbooks/ to ~/.config/Dev10x/playbooks/,
  and databases.yaml from legacy/backup skill directories to
  ~/.config/Dev10x/databases.yaml),
  generalizes session-specific args, enumerates MCP tool globs,
  refreshes script coverage, merges worktree rules, audits for
  friction-causing patterns, and cleans redundant rules from
  project settings files.
  TRIGGER when: plugin version changes, permission prompts keep
  appearing, config files are at old locations, or user asks to
  fix permission friction.
  DO NOT TRIGGER when: permissions are working correctly, or
  you only need a fast bootstrap subset (use
  `dev10x:plugin-maintenance bootstrap` instead).
user-invocable: true
invocation-name: dev10x:upgrade-cleanup
allowed-tools:
  - Skill
  - mcp__plugin_dev10x_cli__record_upgrade
  - Bash(dev10x config migrate:*)
  - Bash(dev10x config migrate-schema:*)
  - Bash(dev10x config migrate-skill-names:*)
  - Read(${CLAUDE_PLUGIN_ROOT}/src/dev10x/core/plugins.yaml)
---

# dev10x:upgrade-cleanup

Top-level entry point for post-upgrade maintenance. The
implementation lives in `dev10x:plugin-maintenance`; this skill
is a thin orchestrator that runs the **full** maintenance pass.

## Why a separate skill

`dev10x:upgrade-cleanup` and `dev10x:onboarding` share the same
underlying maintenance logic but call it with different intent:

| Caller | Mode | Focus |
|--------|------|-------|
| `dev10x:onboarding` | `bootstrap` | Eliminate friction on the demoed skill set out of the box |
| `dev10x:upgrade-cleanup` (this skill) | `full` | Comprehensive post-upgrade hygiene |
| Direct invocation of `dev10x:plugin-maintenance` | either | Manual control |

Keeping `upgrade-cleanup` as a named entry point preserves the
discoverability users expect after running `claude plugin update`,
without forcing them to remember the underlying skill name.

## Execution

Step 1 — migrate legacy Dev10x config out of `~/.claude/` to the
XDG location (`~/.config/Dev10x/` on Linux/macOS, `%APPDATA%/Dev10x/`
on Windows). Idempotent — skips paths already migrated. See GH-215.

```
Bash("dev10x config migrate")
```

Step 1b — convert durable prefs from schema v1 to v2 (GH-1166,
ADR-0022). Independent of Step 1: a config already at the XDG path
can still name a retired preset (`strict` / `guided`) or the
retired `human_review` / `walk_away` keys, which the gate resolver
stops honouring once the legacy translation seam is retired.
Idempotent — a machine already on v2 writes nothing. Every
ambiguous value converts to `supervisor_review: required`, so the
run can only ever add oversight, never remove it.

```
Bash("dev10x config migrate-schema --dry-run")
Bash("dev10x config migrate-schema")
```

Show the dry-run report first — it names each entry's resulting
`supervisor_review`, dropped preset, and added overlays — then
apply.

Step 1c — rewrite skill names that a plugin extraction renamed
(GH-1559, ADR-0034). When a skill moves from `dev10x:<skill>` to
`dev10x-<area>:<skill>`, this rewrites the old name in
`friction.yaml`, `dod-acceptance-criteria.yaml` and the playbook
overrides. Idempotent: a second run reports nothing to migrate.

```
Bash("dev10x config migrate-skill-names --dry-run")
Bash("dev10x config migrate-skill-names")
```

Renaming a config entry does not install the satellite plugin a skill
moved to. When the dry run rewrote a name, or the user asks for a
skill that moved, follow
[`references/satellite-plugins.md`](references/satellite-plugins.md):
it says where the moved skills' grants go and how to check
`enabledPlugins`. Never install a satellite for the user — tell them
the `claude plugin install` command instead; installing is their call.

Step 2 — delegate to the maintenance skill in `full` mode:

```
Skill(skill="dev10x:plugin-maintenance", args="full")
```

The maintenance skill creates its own task list and runs
steps 1–14 sequentially (update paths → migrate configs
including playbook overrides → ensure base perms → generalize →
enumerate MCP → script coverage → worktree merge → permission
audit → clean project files → diff playbooks). The permission
audit hands its findings to `dev10x:permission-audit-apply`, which
applies them one approved fix at a time (GH-1631).

The "Migrate config files" step (step 3) includes two sub-migrations:

1. **Playbook overrides (GH-447):** global playbook overrides from
   `~/.claude/memory/Dev10x/playbooks/` to
   `~/.config/Dev10x/playbooks/`. Regular files are moved; symlinks
   pointing into the new location are deleted; conflicts (destination
   already exists) are surfaced rather than overwritten. The old
   directory is removed once empty.

2. **databases.yaml (GH-446):** stray `databases.yaml` files found in
   legacy or hidden backup skill directories (e.g.,
   `~/.claude/skills/.20260601-1100-backup/*/`) are migrated to
   `~/.config/Dev10x/databases.yaml` — the preferred global location
   since GH-448. The scan uses `find` (not glob `*`) to reach dotted
   directories. Conflicts (destination already exists) are surfaced
   rather than overwritten.

Step 3 — install and register the userspace plugin-load guard
(GH-874). The plugin can be silently skipped at session start by a
Claude Code startup race; a **userspace** SessionStart hook runs even
then and warns the user to reload. See
[`references/plugin-load-race.md`](../../references/plugin-load-race.md)
for the failure mode and diagnosis chain.

Run the three steps in
[`references/plugin-load-guard.md`](references/plugin-load-guard.md):
copy the guard to `~/.claude/hooks/`, register it as a userspace
`SessionStart` hook in `~/.claude/settings.json`, and remove any
registration that points into a versioned plugin-cache path.

After the maintenance pass succeeds, record the plugin version
so the SessionStart install-check stays silent until the next
upgrade:

```
mcp__plugin_dev10x_cli__record_upgrade()
```

The MCP tool reads the version from
`$CLAUDE_PLUGIN_ROOT/.claude-plugin/plugin.json` and writes it
to `~/.config/Dev10x/version.yml` (post-GH-215). Skip this step if the
maintenance pass reported failures — leaving `version.yml`
stale keeps the upgrade prompt visible until the issue is
resolved.

## Auto mode sessions (GH-1868)

In auto mode the classifier can deny reads and writes of the user-level
settings files that Step 2's audit and Step 3's guard registration
touch. Follow [`references/auto-mode.md`](references/auto-mode.md):
restrictive half of a paired edit first, no retry by another route,
hand the exact change to the supervisor, and never put a denied
project rule in the global file instead.

## Post-upgrade verification (GH-1137)

**A clean maintenance log is not proof the upgrade landed.** GH-1136
was invisible for months because `ensure-base` reported "All base
permissions already covered by global settings" while 137 of 285
catalog rules were absent from every project file — a truthful log
and a wrong outcome. Verify against the files, not the log.

Run the four checks in
[`references/post-upgrade-verification.md`](references/post-upgrade-verification.md):
catalog reach across every worktree, no git-tracked settings file
written, the safety-key string values intact (`disableAutoMode` is
opt-out, GH-1856), and a spot-check that a sanctioned command
does not prompt.

## Configuration

See `dev10x:plugin-maintenance` for `projects.yaml` location
and base-permission semantics. Post-GH-215 the userspace config
path is `~/.config/Dev10x/upgrade-cleanup-projects.yaml`. Old
files at `~/.claude/skills/Dev10x:upgrade-cleanup/projects.yaml`
and `~/.claude/memory/Dev10x/*` are migrated lazily on first
read and explicitly by `dev10x config migrate`.
