# Configuration Resolution

Central reference for Dev10x configuration file paths, resolution
order, and project mapping format.

## Where the Dev10x config root lives

Throughout this doc and Dev10x skills, `<Dev10x config>` is the
canonical placeholder for the user-global config root. It resolves
per platform (and overrides):

| Resolution order | Path | When |
|---|---|---|
| 1 (override) | `$DEV10X_CONFIG_HOME` | Set explicitly (tests, CI, custom layouts) |
| 2 (override) | `$XDG_CONFIG_HOME/Dev10x` | `XDG_CONFIG_HOME` is set |
| 3 (Windows) | `%APPDATA%/Dev10x` | e.g. `C:\Users\<name>\AppData\Roaming\Dev10x` |
| 4 (default) | `~/.config/Dev10x` | Linux, macOS, BSDs |

Source of truth: `src/dev10x/domain/dev10x_paths.py` (`_platform_default_root`).
When examples in this doc or SKILL.md files write
`~/.config/Dev10x/...`, that is the Linux/macOS form — substitute
the platform-appropriate root from the table above.

## Three-Tier Resolution

All Dev10x configuration files follow a consistent resolution order
(project-local → global → plugin defaults):

| Priority | Location | Scope | Committed? |
|----------|----------|-------|------------|
| 1 (highest) | `.claude/Dev10x/` | Project-local | No (gitignored) |
| 2 | `~/.config/Dev10x/` (XDG; legacy `~/.claude/memory/Dev10x/`) | Global with repo mapping | N/A (user home) |
| 3 (lowest) | `${CLAUDE_PLUGIN_ROOT}/skills/*/references/` | Plugin defaults | Yes (plugin repo) |

**Tier 1 — Project-local** (`.claude/Dev10x/`):
Runtime and session data. Highest priority for truly project-specific
overrides that should not be shared across repos. Gitignored.

**Tier 2 — Global with repo mapping** (`~/.config/Dev10x/`):
Single file serves multiple projects via `projects[].match` globs.
Preferred for overrides that apply to several repos (e.g., all
ExampleCorp repos share the same shipping pipeline).

> **Note (GH-941):** The old `~/.claude/projects/<key>/memory/`
> path is removed. All tier 2 config lives under
> `~/.config/Dev10x/`.
>
> **Note (GH-215):** Dev10x userspace config moved out of
> `~/.claude/` to the XDG location: `~/.config/Dev10x/` on
> Linux/macOS, `%APPDATA%/Dev10x/` on Windows. Override via
> `DEV10X_CONFIG_HOME`. Legacy paths under `~/.claude/memory/Dev10x/`
> and `~/.claude/Dev10x/` are migrated lazily on first read and
> explicitly by `dev10x config migrate` (wired into
> `Dev10x:upgrade-cleanup` and `Dev10x:plugin-doctor`).

**Tier 3 — Plugin defaults** (`${CLAUDE_PLUGIN_ROOT}/skills/*/references/`):
Shipped with the plugin. Used when no user override exists.

## Project Mapping Format

Global config files (Tier 2) use a `projects` list with glob
matching on the repo's `nameWithOwner` (e.g., `org/repo`).
Match uses standard Unix glob syntax (`fnmatch`): `*` matches any
string, `?` matches a single character, `[seq]` matches any character
in *seq*.

```yaml
projects:
  - match: "Dev10x-Guru/dev10x-claude"
    # config specific to this repo

  - match: "org/*"
    # config shared across all ExampleCorp repos
```

**Resolution within Tier 2:**
1. Get current repo: `git remote get-url origin` → extract `owner/repo`
2. Walk the `projects` list — first `match` glob that fits selects
   the config block
3. If no match, skip Tier 2 (fall through to Tier 3 or 4)

This follows the same pattern as `gitmoji.yaml` project overrides.

## Configuration Files

### Playbooks

| Tier | Path | Format |
|------|------|--------|
| 1 | `.claude/Dev10x/playbooks/<key>.yaml` | Standard playbook YAML |
| 2 | `~/.config/Dev10x/playbooks/<key>.yaml` | Playbook + `projects` mapping |
| 3 | `${CLAUDE_PLUGIN_ROOT}/skills/<key>/references/playbook.yaml` | Default playbook |

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
  - match: "Dev10x-Guru/dev10x-claude"
    active_modes: [solo-maintainer]
    overrides:
      - play: feature
        steps:
          - subject: Set up workspace
            type: detailed
            skills: [dev10x:ticket-branch]
          # ...

  - match: "example-org/*"
    active_modes: [solo-maintainer]
    overrides:
      - play: feature
        steps: [...]
```

**Resolution order:** Check Tier 1 first, then Tier 2 with repo
matching, then Tier 3 (plugin defaults).

### Session Config

| Tier | Path | Notes |
|------|------|-------|
| 1 only | `.claude/Dev10x/session.yaml` | Session-scoped, not shared |

Session config is always project-local. It contains runtime state
(friction level, active modes) that is session-specific.

### PR Merge Settings

| Tier | Path | Format |
|------|------|--------|
| 2 | `~/.config/Dev10x/settings-pr-merge.yaml` | Settings + `projects` mapping |

**Global format** (Tier 2):

```yaml
# ~/.config/Dev10x/settings-pr-merge.yaml
projects:
  - match: "Dev10x-Guru/*"
    strategy: rebase
    delete_branch: true
    solo_maintainer: true
  - match: "example-org/*"
    strategy: rebase
    delete_branch: true
    solo_maintainer: true
```

### Acceptance Criteria


| Tier | Path |
|------|------|
| 2 | `~/.config/Dev10x/dod-acceptance-criteria.yaml` |
| 3 | Plugin defaults (hardcoded in skill) |

### Gitmoji Overrides


| Tier | Path |
|------|------|
| 2 | `~/.config/Dev10x/gitmoji.yaml` |
| 3 | `${CLAUDE_PLUGIN_ROOT}/skills/git-commit/references/gitmoji-defaults.yaml` |

### Database Schema

| Tier | Path |
|------|------|
| 2 | `~/.config/Dev10x/db-<name>-schema.md` |

### GitHub Reviewers

| Tier | Path |
|------|------|
| 2 | `~/.config/Dev10x/github-reviewers-config.yaml` |

### Slack Config

| Tier | Path |
|------|------|
| 2 | `~/.config/Dev10x/slack-config.yaml` |

### Slack Code Review Requests

| Tier | Path |
|------|------|
| 2 | `~/.config/Dev10x/slack-config-code-review-requests.yaml` |

### Database Connections

| Tier | Path |
|------|------|
| 2 | `~/.config/Dev10x/databases.yaml` |

## Skills That Reference These Paths

| Skill | Config type | Tiers used |
|-------|------------|------------|
| `Dev10x:work-on` | playbook, session | 1, 2, 3 |
| `Dev10x:playbook` | playbook | 1, 2, 3 |
| `Dev10x:gh-pr-respond` | playbook | 1, 2, 3 |
| `Dev10x:release-notes` | playbook | 1, 2, 3 |
| `Dev10x:investigate` | playbook | 1, 2, 3 |
| `Dev10x:gh-pr-merge` | settings | 2 |
| `Dev10x:verify-acc-dod` | acceptance criteria | 2, 3 |
| `Dev10x:git-commit` | gitmoji | 2, 3 |
| `Dev10x:gh-pr-request-review` | reviewers | 2 |
| `Dev10x:db` | schema, databases | 2 |
| `Dev10x:db-psql` | databases | 2 |
| `Dev10x:slack` | slack-config | 2 |
| `Dev10x:slack-setup` | slack-config | 2 |
| `Dev10x:slack-review-request` | slack-config | 2 |
| `Dev10x:request-review` | reviewers, slack-config | 2 |
| `Dev10x:fanout` | session | 1 |
