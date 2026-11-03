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

Source of truth: `src/dev10x/core/domain/dev10x_paths.py` (`_platform_default_root`).
When examples in this doc or SKILL.md files write
`~/.config/Dev10x/...`, that is the Linux/macOS form — substitute
the platform-appropriate root from the table above.

**From the shell**, the resolved root is available as the
bare-invocation output of the `dev10x` CLI:

```bash
$(uvx dev10x)/gitmoji.yaml
# → /home/<user>/.config/Dev10x/gitmoji.yaml on Linux
# → /Users/<user>/.config/Dev10x/gitmoji.yaml on macOS
# → C:\Users\<user>\AppData\Roaming\Dev10x\gitmoji.yaml on Windows
```

`dev10x config root` is the explicit equivalent — both print
the same path. Use whichever reads better in your script.

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
> `dev10x:upgrade-cleanup` and `dev10x:plugin-doctor`).

**Tier 3 — Plugin defaults** (`${CLAUDE_PLUGIN_ROOT}/skills/*/references/`):
Shipped with the plugin. Used when no user override exists.

## Project Mapping Format

Global config files (Tier 2) use a `projects` list whose entries carry a
glob. **Two addressing schemes exist, and the key name says which**
(ADR-0026):

| Key | Compared against | Files |
|---|---|---|
| `match_repo:` | the repo's `nameWithOwner` — `org/repo` | `playbooks/<skill>.yaml`, `settings-pr-merge.yaml`, `gitmoji.yaml` |
| `match:` | an **absolute directory path** | `friction.yaml` |

Both use standard Unix glob syntax (`fnmatch`): `*` matches any string
— **including `/`** — `?` matches a single character, `[seq]` matches
any character in *seq*.

> **`match:` is no longer read in a repo-addressed file** (GH-1771).
> An entry that still carries only `match:` selects nothing.
> Rename it to `match_repo:`.
> `dev10x config doctor` and `dev10x playbook diff` report every entry
> still on the retired key.

```yaml
projects:
  - match_repo: "Dev10x-Guru/dev10x-claude"
    # config specific to this repo

  - match_repo: "org/*"
    # config shared across all ExampleCorp repos
```

**Resolution within Tier 2 (repo-addressed files):**
1. Get current repo: `git remote get-url origin` → extract `owner/repo`
2. Walk the `projects` list — first `match_repo` glob that fits selects
   the config block (an entry with only `match:` is skipped)
3. If no match, skip Tier 2 (fall through to Tier 3 or 4)

**No `origin` remote.** Step 1 has a failure case: a local-only repo, a
clone whose remote is named something other than `origin`, or a
detached checkout has no `owner/repo` to extract. Tier 2 is then **not
evaluated at all** — which is a different outcome from "evaluated, no
entry matched", and the tools say which: `dev10x config doctor` reports
the list as NOT evaluated and names the reason. Repo-addressed Tier 2
config cannot apply to such a checkout; move the settings to Tier 1
(`.claude/Dev10x/`) or add an `origin` remote.

### The portable `*/<repo>` form

Because `fnmatch`'s `*` spans `/`, a glob written `*/<repo>` resolves
under **both** schemes: it matches `owner/repo` with `*` absorbing the
owner, and `/work/dx/repo` with `*` absorbing the parent directories.
An org-form glob does not travel — `Dev10x-Guru/*` never matches a
directory path — which is exactly the mistake the two key names now
make visible.

Treat `*/<repo>` as a convenience, not a contract: the overlap holds
because of `fnmatch` semantics, not by design. The named keys are the
guarantee.

## Configuration Files

The per-file tiers, paths and formats — playbooks, `friction.yaml`,
PR merge settings, acceptance criteria, gitmoji, database schema and
connections, GitHub reviewers, Slack and plugin-maintenance
preferences — are in [`config-files.md`](config-files.md) (GH-1785).

A config file that keeps its name moving out of the legacy
`~/.claude/memory/Dev10x/` directory needs no migration entry:
`dev10x config migrate` sweeps that directory for `*.yaml` / `*.yml`
and copies each to the same name under `<Dev10x config>`. Only a file
that is renamed or comes from elsewhere is listed by hand in
`_relocated_pairs()` (`src/dev10x/core/domain/dev10x_paths.py`).

## Skills That Reference These Paths

| Skill | Config type | Tiers used |
|-------|------------|------------|
| `dev10x:work-on` | playbook, session | 1, 2, 3 |
| `dev10x:playbook` | playbook | 1, 2, 3 |
| `dev10x:gh-pr-respond` | playbook | 1, 2, 3 |
| `dev10x:release-notes` | playbook | 1, 2, 3 |
| `dev10x:investigate` | playbook | 1, 2, 3 |
| `dev10x:gh-pr-merge` | settings | 2 |
| `dev10x:verify-acc-dod` | acceptance criteria | 2, 3 |
| `dev10x:git-commit` | gitmoji | 2, 3 |
| `dev10x:gh-pr-request-review` | reviewers | 2 |
| `dev10x-db:db` | schema, databases | 2 |
| `dev10x-db:db-psql` | databases | 2 |
| `dev10x:slack` | slack-config | 2 |
| `dev10x:slack-setup` | slack-config | 2 |
| `dev10x:slack-review-request` | slack-config | 2 |
| `dev10x:request-review` | reviewers, slack-config | 2 |
| `dev10x:fanout` | session | 1 |
| `dev10x:plugin-maintenance` | preferences | 2 |
