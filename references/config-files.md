# Dev10x Configuration Files

Per-file tiers, paths and formats for every Dev10x configuration file.
The resolution rules these tables apply — where `<Dev10x config>`
lives, the three tiers, and how `projects[]` entries are matched — are
in [`config-resolution.md`](config-resolution.md). Split out of it to
keep both inside the 200-line reference budget (GH-1785).

## Playbooks

| Tier | Path | Format |
|------|------|--------|
| 1 | `.claude/Dev10x/playbooks/<key>.yaml` | Standard playbook YAML |
| 2 | `~/.config/Dev10x/playbooks/<key>.yaml` | Playbook + `projects` mapping |
| 3 | `${CLAUDE_PLUGIN_ROOT}/skills/<key>/references/playbook.yaml` | Default playbook |

A key with no dedicated tier-3 file (`work-on`) uses the shared
default: the core mechanism file
`skills/playbook/references/playbook.yaml` merged with each plugin's
`skills/*/references/playbook.d/<plugin>.yaml` fragment, core first and
then in `plugins.yaml` order (GH-1555, ADR-0034 Stage A3). The work-on
plays are in `skills/work-on/references/playbook.d/coding.yaml`.

**Global playbook format** (Tier 2):

```yaml
# ~/.config/Dev10x/playbooks/work-on.yaml

fragments:
  shipping-pipeline-solo:
    - subject: Code review
      type: detailed
      skills: [dev10x:review, dev10x:review-fix]
    # ...

projects:
  - match_repo: "Dev10x-Guru/dev10x-claude"
    active_modes: [solo-maintainer]
    overrides:
      - play: feature
        steps:
          - subject: Set up workspace
            type: detailed
            skills: [dev10x:ticket-branch]
          # ...

  - match_repo: "example-org/*"
    active_modes: [solo-maintainer]
    overrides:
      - play: feature
        steps: [...]
```

**Resolution order:** Check Tier 1 first, then Tier 2 with repo
matching, then Tier 3 (plugin defaults).

## Session Config

| Tier | Path | Notes |
|------|------|-------|
| 2 only | `~/.config/Dev10x/friction.yaml` | Global, keyed by `projects[].match` dir globs |

This is the one file whose `match:` is **not** an `org/repo` glob — it
is compared against the checkout's absolute directory path, keyed by
the git common dir so one entry covers every worktree (ADR-0018 D3).
Copying a `Dev10x-Guru/*` glob here selects nothing.

Session prefs are **not** project-local (ADR-0018 D1). `friction_level`,
`active_modes`, `allowed_overlays`, and the `gate_*` keys live in one
global file keyed by directory-path globs, so a repo's prefs cover
every worktree by construction. Read them via
`mcp__plugin_dev10x_cli__resolve_gate`, which owns the precedence.

The retired `.claude/Dev10x/session.yaml` is not a tier: ADR-0018 D2
removed it as a config source, and D5 moved its remaining task-index
role to `~/.config/Dev10x/task-index/<repo-stem>.yaml` (reached via the
`task_index_*` MCP tools, never Write/Edit).

## PR Merge Settings

| Tier | Path | Format |
|------|------|--------|
| 2 | `~/.config/Dev10x/settings-pr-merge.yaml` | Settings + `projects` mapping |

**Global format** (Tier 2):

```yaml
# ~/.config/Dev10x/settings-pr-merge.yaml
projects:
  - match_repo: "Dev10x-Guru/*"
    strategy: rebase
    delete_branch: true
    solo_maintainer: true
  - match_repo: "example-org/*"
    strategy: rebase
    delete_branch: true
    solo_maintainer: true
```

## Acceptance Criteria

| Tier | Path |
|------|------|
| 2 | `~/.config/Dev10x/dod-acceptance-criteria.yaml` |
| 3 | Plugin defaults (hardcoded in skill) |

Tier 2 is the only location `dev10x:verify-acc-dod` reads or writes.
The retired `~/.claude/memory/Dev10x/dod-acceptance-criteria.yaml` is
not read; `dev10x config migrate` copies it to tier 2.

## Gitmoji Overrides

| Tier | Path |
|------|------|
| 2 | `~/.config/Dev10x/gitmoji.yaml` |
| 3 | `${CLAUDE_PLUGIN_ROOT}/skills/git-commit/references/gitmoji-defaults.yaml` |

## Database Schema

| Tier | Path |
|------|------|
| 2 | `~/.config/Dev10x/db-<name>-schema.md` |

## GitHub Reviewers

| Tier | Path |
|------|------|
| 2 | `~/.config/Dev10x/github-reviewers-config.yaml` |

## Slack Config

| Tier | Path |
|------|------|
| 2 | `~/.config/Dev10x/slack-config.yaml` |

## Slack Code Review Requests

| Tier | Path |
|------|------|
| 2 | `~/.config/Dev10x/slack-config-code-review-requests.yaml` |

## Plugin Maintenance Preferences

| Tier | Path |
|------|------|
| 2 | `~/.config/Dev10x/plugin-maintenance-prefs.yaml` |

Valid values for `update_preference`: `both | plugin | uv | skip | ask`.
When absent or set to `ask`, `dev10x:plugin-maintenance` prompts on
every run. Legacy path `~/.claude/memory/Dev10x/plugin-maintenance-prefs.yaml`
is migrated lazily on first read.

## Database Connections

`databases.yaml` stores named database entries for `dev10x:db-psql`.
The script resolves config from multiple locations so project plugins
(e.g., `tt:db`) are discovered automatically without symlinks.

| Priority | Path | Notes |
|----------|------|-------|
| 1 | `$DB_CONFIG` | Explicit override; skips all other locations |
| 2 | `${CLAUDE_PLUGIN_ROOT}/skills/db-psql/databases.yaml` | Plugin-shipped defaults |
| 3 | `~/.config/Dev10x/databases.yaml` | **Preferred** user-global location (XDG) |
| 4 | `~/.claude/memory/Dev10x/databases.yaml` | Deprecated fallback (kept for backward compat) |
| 5 | `skills/*/databases.yaml` | Sibling skills in the same plugin |
| 6 | `~/.claude/skills/*/databases.yaml` | User-installed standalone skills |
| 7 | `~/.claude/plugins/marketplaces/*/skills/*/databases.yaml` | Other marketplace plugins |

**Recommended setup**: place your user-level `databases.yaml` at
`~/.config/Dev10x/databases.yaml` (priority 3). The legacy
`~/.claude/memory/Dev10x/databases.yaml` path still works but is
deprecated; migrate to the XDG location when convenient.

`$DB_CONFIG` env-var override is not recommended in Claude Code
sessions — prefixing a `DB_CONFIG=...` env var shifts the effective
command prefix and breaks allow-rule matching (see GH-448).
