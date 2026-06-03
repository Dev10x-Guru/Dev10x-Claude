---
name: Dev10x:upgrade-cleanup
description: >
  Post-upgrade cleanup entry point — delegates to
  `Dev10x:plugin-maintenance` in `full` mode. Updates plugin
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
  `Dev10x:plugin-maintenance bootstrap` instead).
user-invocable: true
invocation-name: Dev10x:upgrade-cleanup
allowed-tools:
  - Skill
  - mcp__plugin_Dev10x_cli__record_upgrade
  - Bash(dev10x config migrate:*)
---

# Dev10x:upgrade-cleanup

Top-level entry point for post-upgrade maintenance. The
implementation lives in `Dev10x:plugin-maintenance`; this skill
is a thin orchestrator that runs the **full** maintenance pass.

## Why a separate skill

`Dev10x:upgrade-cleanup` and `Dev10x:onboarding` share the same
underlying maintenance logic but call it with different intent:

| Caller | Mode | Focus |
|--------|------|-------|
| `Dev10x:onboarding` | `bootstrap` | Eliminate friction on the demoed skill set out of the box |
| `Dev10x:upgrade-cleanup` (this skill) | `full` | Comprehensive post-upgrade hygiene |
| Direct invocation of `Dev10x:plugin-maintenance` | either | Manual control |

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

Step 2 — delegate to the maintenance skill in `full` mode:

```
Skill(skill="Dev10x:plugin-maintenance", args="full")
```

The maintenance skill creates its own task list and runs
steps 1–14 sequentially (update paths → migrate configs
including playbook overrides → ensure base perms → generalize →
enumerate MCP → script coverage → worktree merge → permission
audit → clean project files → diff playbooks).

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

After the maintenance pass succeeds, record the plugin version
so the SessionStart install-check stays silent until the next
upgrade:

```
mcp__plugin_Dev10x_cli__record_upgrade()
```

The MCP tool reads the version from
`$CLAUDE_PLUGIN_ROOT/.claude-plugin/plugin.json` and writes it
to `~/.config/Dev10x/version.yml` (post-GH-215). Skip this step if the
maintenance pass reported failures — leaving `version.yml`
stale keeps the upgrade prompt visible until the issue is
resolved.

## Configuration

See `Dev10x:plugin-maintenance` for `projects.yaml` location
and base-permission semantics. Post-GH-215 the userspace config
path is `~/.config/Dev10x/upgrade-cleanup-projects.yaml`. Old
files at `~/.claude/skills/Dev10x:upgrade-cleanup/projects.yaml`
and `~/.claude/memory/Dev10x/*` are migrated lazily on first
read and explicitly by `dev10x config migrate`.
