---
name: Dev10x:upgrade-cleanup
description: >
  Post-upgrade cleanup entry point — delegates to
  `Dev10x:plugin-maintenance` in `full` mode. Updates plugin
  version paths, ensures base permissions, migrates config files,
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

Delegate to the maintenance skill in `full` mode:

```
Skill(skill="Dev10x:plugin-maintenance", args="full")
```

The maintenance skill creates its own task list and runs
steps 1–9 sequentially (update paths → migrate configs →
ensure base perms → generalize → enumerate MCP → script
coverage → worktree merge → permission audit → clean project
files).

## Configuration

See `Dev10x:plugin-maintenance` for `projects.yaml` location
and base-permission semantics. The userspace config path
(`~/.claude/skills/Dev10x:upgrade-cleanup/projects.yaml`) is
unchanged for backward compatibility.
