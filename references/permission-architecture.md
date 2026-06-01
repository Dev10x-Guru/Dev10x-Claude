# Permission Architecture

How Claude Code evaluates tool requests, and how hooks interact
with the permission layer.

## Execution Order

When an agent requests a tool call (e.g., `Bash(git push origin)`),
Claude Code processes it in this order:

```
Agent requests tool call
  │
  ├─ 1. Deny rules  → if matched, BLOCKED (hooks never run)
  ├─ 2. Allow rules  → if matched, ALLOWED silently
  ├─ 3. Ask rules    → if matched, user prompted
  ├─ 4. No rule match → generic permission prompt
  │
  └─ 5. PreToolUse hooks run (only if steps 1-4 allowed)
         └─ Hook can BLOCK with systemMessage
         └─ Hook can ALLOW (or not respond)
```

**Key insight:** Hooks only execute after the permission layer
passes. A deny rule prevents both the tool call AND the hook.
An allow rule silences the permission prompt AND enables the hook.

## Hook-Enabled Allow Rules

Some allow rules exist not to permit the command, but to ensure
a PreToolUse hook can fire its redirect message. Without the
allow rule, step 4 fires a generic "approve?" prompt before the
hook runs at step 5.

### SkillRedirectValidator

The `SkillRedirectValidator` hook blocks raw CLI commands and
redirects to skill equivalents with educational messages:

| Allow rule | Hook blocks | Redirects to | Guardrails |
|-----------|-------------|-------------|------------|
| `Bash(gh pr create:*)` | `gh pr create` | `Dev10x:gh-pr-create` | Job Story, ticket linking |
| `Bash(git push:*)` | `git push` | `Dev10x:git` | Protected branches, force-push safety |
| `Bash(git rebase -i:*)` | `git rebase -i` | `Dev10x:git-groom` | Atomic commits, conventions |
| `Bash(git commit -m:*)` | `git commit -m` | `Dev10x:git-commit` | Gitmoji, JTBD title, 72-char |
| `Bash(gh pr checks:*)` | `gh pr checks --watch` | `Dev10x:gh-pr-monitor` | Failure detection, fixups |

These allow rules are classified as `HOOK_ENABLED` in permission
audits. Removing them degrades UX — the user sees a generic
permission prompt instead of an educational redirect.

### Adding New Hook-Enabled Rules

When adding a new SkillRedirectValidator entry:

1. Add the regex pattern to `skill_redirect.py`
2. Add the corresponding allow rule to `settings.json`
3. Add the pattern to `HOOK_ENABLED_PATTERNS` in
   `clean-project-files.py` so it isn't stripped as redundant
4. Verify the redirect message fires correctly

## Implications for Tooling

| Tool | Implication |
|------|------------|
| `permission-auditor` agent | Must classify hook-enabled rules as `HOOK_ENABLED`, not `DEAD_RULE` |
| `clean-project-files.py` | Must detect and skip hook-enabled rules during cleanup |
| `plugin-maintenance` skill (invoked directly or via `upgrade-cleanup`) | Must not strip hook-enabled rules from project settings |

## Proactive Safe-Command Allowlist (GH-310)

An unsupervised (adaptive / AFK) session treats every permission
prompt as a **hard stop** — there is no human to answer it, so the
session cannot complete. The same prompt is also the trigger for
Claude Code's option-2 "Yes, and don't ask again for…" feature,
which strips a command down to its broadest prefix and writes a
catch-all `Bash(<verb> *)` rule into the user's allow list.

### Why deny rules cannot fix the footgun

A natural instinct is to ship `deny` rules for the catch-all shapes
(`Bash(git *)`, `Bash(gh *)`, …). This **backfires**. Claude Code
evaluates rules in the order `deny → ask → allow`, and the first
match wins, so a deny always beats a more-specific allow. The space
in `Bash(git *)` is a trailing wildcard equivalent to `:*`, so the
pattern matches **every** `git <args>` command. A `deny: Bash(git *)`
would therefore also block `git status`, `git log`, and every other
git subcommand — for every plugin user — even with
`allow: Bash(git status:*)` present.

Source: [Claude Code permissions docs](https://code.claude.com/docs/en/permissions.md)
— "Rules are evaluated `deny → ask → allow`; the first matching rule
wins" and "`Bash(git *)` matches `git log --oneline --all`".

### The fix: pre-approve the safe surface

The only safe defense is to **enumerate the safe commands as `allow`
rules** so the prompt never fires and option-2 never gets the chance
to write a catch-all. The catalog lives in
`skills/upgrade-cleanup/projects.yaml` under `base_permissions:` and
is propagated into each project's `settings.local.json` by
`uvx dev10x permission ensure-base`.

What belongs in the catalog (safe to auto-approve):

- Read-only filesystem / text inspection (`ls`, `cat`, `grep`, `rg`,
  `stat`, `wc`, `diff`, …) — never mutate state.
- `--version` / `--help` info flags for execution-capable verbs.
- Read-only subcommands of rich verbs (`git show`, `git rev-parse`,
  `gh release view`, `gh workflow list`, `uv pip list`, …).

What is deliberately excluded (keeps prompting, routes to a skill,
or is forbidden by a hook):

- Arbitrary code execution — `python -c`, `sh -c`, `bash -c`,
  `eval`, and package runners (`npx <pkg>`, `pnpm dlx <pkg>`,
  `pipx run <pkg>`, `bunx <pkg>`).
- Network fetch-and-exec or exfiltration — `curl <url>`,
  `wget <url>` (only `--version` is allowed).
- Destructive filesystem operations.
- Env-prefixed commands (`env VAR=x cmd`) — tracked under GH-311.
- The bare-verb catch-alls themselves (`Bash(git *)`, etc.).

The upstream UI defect that generates the catch-all is tracked
separately (GH-312); this allowlist is the defense-in-depth that
keeps unattended sessions moving without it.

### WebFetch documentation domains (GH-369)

`WebFetch` is its own permission entity class, distinct from `Bash`.
A rule has the shape `WebFetch(domain:<host>)` and matches a single
fully-qualified host over HTTPS. Routine documentation lookups (read
the Django docs, check a Pydantic page, open an MDN article) prompt
per-domain on first access — GH-271 evidence recorded 6+ distinct doc
domains in one session, each a fresh stall for an unattended run.

The `webfetch-public-docs` group (tier 2) pre-approves a curated set
of ~30 canonical documentation hosts so these fetches never prompt.
Scope rules for the catalog:

- **HTTPS documentation hosts only** — reference content, not API
  endpoints. A docs host serves read-only pages; pre-approving it
  cannot fetch-and-exec or exfiltrate.
- **One FQDN per rule** — `WebFetch(domain:docs.python.org)`, not a
  wildcard `*.python.org`. Explicit hosts keep the approved surface
  auditable and prevent a broad subdomain from silently covering an
  API or upload endpoint.
- **Not for arbitrary URLs** — fetching a non-doc host still prompts,
  by design. The catalog is a curated allowlist, not a blanket
  WebFetch permit.

## Permission Group Tier Assignment

Each group in `baseline-permissions.yaml` is assigned a tier that determines
whether it ships as a plugin default or requires user opt-in.

| Tier | Scope | Shipped By | Examples |
|------|-------|-----------|----------|
| 1 | Universal dev tools | Plugin (always) | git, gh, uv, ls, cat, grep |
| 2 | Routine doc/ref fetches, plugin infrastructure | Plugin (always) | webfetch-public-docs, dev10x-cli, mktmp |
| 3 | Project-specific or cost-bearing | User projects (projects.yaml) | railway-cli, obsidian-cli |

**Tier 1 criteria**: Commands present in every development workflow, safe to
auto-approve unconditionally. Examples: `git show`, `gh issue view`,
`uv pip list`.

**Tier 2 criteria**: Routine commands that would prompt every session without
pre-approval, stalling unattended runs. Primary drivers: GH-271 evidence
(6+ doc domains in one session, multiple plugin scripts). Not universal across
all projects, but frequent enough that pre-approval prevents friction. Scoped
conservatively to read-only surfaces (doc hosts, not API endpoints).

**Tier 3 criteria**: Project-specific tooling, cost-bearing (CI triggers),
or infrastructure tied to specific deployments. Examples: Railway deployment
CLI (org-specific), Obsidian vault CLI (project-specific). Opt-in via user
config in `projects.yaml` § `base_permissions` for projects that need them.

### Review Checklist for New Groups

When evaluating a new permission group:

- **Tier 1**: Only add if the command is present in 90%+ of projects
- **Tier 2**: Justify via GH-271 friction evidence — how often would this
  stall? Include evidence from issue/PR discussion (e.g., "6+ doc domains hit")
- **Tier 3**: Document why the group is project-specific; confirm no universal use

## Docs-vs-Evidence Caveat (finding #47)

Official Claude Code docs state that permission rules merge across
scopes rather than override ("rules from global settings are inherited
into project settings"). **Treat this as intended, not actual
behavior.**

Empirical evidence from [#47](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/47)
(closed by [#50](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/50))
establishes the opposite: when a project has its own
`settings.local.json`, the **local file wins** and global rules are
not always inherited. Practical consequences:

- A project-level rule that is an exact duplicate of a global rule is
  NOT necessarily redundant — the project copy may be the only active
  copy for that project's sessions.
- `dev10x permission clean` removes exact duplicates of global rules
  by default (historical behavior). Use `--skip-global-dedup` to
  suppress this when inheritance cannot be verified.
- The `permission-investigator` skill and `permission-auditor` agent
  are the authoritative sources for per-project rule coverage; trust
  their output over the upstream documentation.

**Rule of thumb:** do not cite the "permissions merge" docs as a
reason to remove a project rule. Run `dev10x permission investigate`
or check `permission-auditor` findings instead.

## Hook Load-Once Semantics (GH-407)

Claude Code loads hooks **once at session start** from
``$CLAUDE_PLUGIN_ROOT``. An on-disk ``claude plugin update``
installs a newer version into the cache but does **not** hot-swap
the running hooks — the session continues executing the pre-upgrade
hooks until it is restarted.

Practical implications:

- A shipped bug-fix in a validator (e.g., DX012 `safe-expansion`
  for single-quoted brace expressions) is dormant in sessions that
  predated the upgrade. The fix tests green in CI but still produces
  friction in those live sessions.
- The stale hooks can inflate friction evidence: a false-positive that
  a newer validator suppresses still fires in old sessions, making it
  look like an unfixed regression.
- The **settings-staleness** check (`build_install_check_context`) and
  the **running-hook** check (`build_hook_version_drift_context`) are
  distinct. Settings can be refreshed by upgrade-cleanup without
  restarting the session; the running hooks remain stale until restart.

The **hook version drift detector** (SessionStart feature
`session-hook-version-drift`) addresses this:

1. Reads the running version from ``$CLAUDE_PLUGIN_ROOT/plugin.json``
   (set by Claude Code at session start).
2. Scans ``~/.claude/plugins/cache/<publisher>/<slug>/`` for the
   highest-installed version.
3. On mismatch, emits:
   *"Dev10x hooks running v0.72.0 but v0.76.0 is installed on disk.
   Restart this session (or run `/Dev10x:upgrade-cleanup`) to activate
   shipped friction fixes, validators, and catalog improvements."*
4. Returns an empty string when running == latest or when either
   version is unresolvable (``--plugin-dir`` dev installs bypass the
   cache, so no drift signal is raised).

**Regression note:** when a "shipped fix still fails" report arrives,
check hook-version drift *before* assuming a logic regression. Confirm
the session was started after the fix was installed by comparing the
running-hook version against the fix's release tag.

## References

- [ADR-0003](../docs/adr/0003-allow-rules-as-hook-enablers.md) — decision record
- `hooks/scripts/bash_validators/skill_redirect.py` — the hook implementation
- `agents/permission-auditor.md` — audit agent with `HOOK_ENABLED` classification
- `references/permission-safe-flags.md` — flag-overrides pattern for safe flags
