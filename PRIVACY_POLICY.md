# Privacy Policy

**Effective date:** 2026-04-19
**Project:** Dev10x Claude Plugin (`Dev10x-Guru/dev10x-claude`)

## Scope

This policy covers the Dev10x plugin distributed through this
repository.
It does not cover the Anthropic Claude Code host, third-party
services you authenticate against (GitHub, Linear, JIRA, Slack,
Sentry, AWS), or the `dev10x.guru` marketing site.

## What the plugin collects

The plugin runs entirely on your local machine.
Everything it writes stays on disk under paths you control:

| Data | Location | Purpose |
|------|----------|---------|
| Session state (task lists, plan context, session IDs) | `~/.claude/projects/<project>/` | Survive context compaction; resume prior sessions |
| Auto-memory notes (per project) | `~/.claude/projects/<project>/memory/` | Preferences and feedback you asked Claude to remember |
| Global Dev10x config (playbook overrides) | `~/.claude/memory/Dev10x/` | Shared workflow customizations |
| Hook timing & outcome audit records | `/tmp/Dev10x/logs/hooks-YYYY-MM-DD.jsonl` | Debug and performance analysis of hook execution |
| Temporary working files | `/tmp/Dev10x/` | Short-lived scratch files (commit messages, etc.) |
| Per-project config (playbooks, session settings) | `.claude/Dev10x/` in your repos | Project-scoped workflow overrides |

Audit log records contain: tool name, event phase, duration,
exit code, and a span identifier.
They do not contain command payloads, file contents, or secrets.
The retention target is 30 days
(`DEV10X_HOOK_AUDIT_RETAIN_DAYS`); pruning is a manual operation
you run when convenient via `dev10x hook audit-prune`.

Audit collection can be disabled by exporting
`DEV10X_HOOK_AUDIT=0`.

## What the plugin does not collect

- No telemetry is sent to the plugin authors.
- No analytics, tracking pixels, or usage metrics leave your
  machine.
- No user identifiers, emails, or profile data are harvested.
- No file contents, command output, or source code are uploaded.
- Hooks, validators, and MCP servers make no outbound network
  calls other than those you explicitly invoke (for example,
  `git push`, `gh pr create`, or an authenticated MCP tool
  request).
- Some **skill scripts** (e.g., `qa-self/upload-screenshots.py`)
  call documented integrations directly via HTTP libraries when
  you invoke the skill. The targeted services are listed in the
  table below; no other outbound calls are made.

## Third-party integrations

Some skills integrate with external services.
These services only receive data when you invoke them and only
with credentials you supply:

| Integration | Credentials | Data exchanged |
|-------------|-------------|----------------|
| GitHub (`gh` CLI, MCP) | Your GitHub token | Issue / PR payloads you explicitly create or fetch |
| GitHub App API (`dev10x github-app setup` wizard) | App ID + private key you provide | Direct calls to `api.github.com` to verify the App key matches, list installations, exchange a JWT for an installation token, and read one repo per installation before writing config |
| Linear (MCP) | Your Linear OAuth session | Issues and comments you read or write |
| JIRA (`Dev10x:jira`) | API token from your OS keyring | Issue lookups and comments you request |
| Slack (MCP) | Your Slack app token | Channel reads and messages you post |
| Google Chat (`Dev10x:gchat`) | Service-account key from your OS keyring | Direct calls to `chat.googleapis.com` (via `oauth2.googleapis.com` for a token) to post review-request messages you approve to your configured Chat space |
| Sentry (MCP) | Your Sentry auth | Issue details you fetch |
| AWS Secrets Manager (`aws-vault`) | Your AWS profile | Secret lookups you approve |
| Kubernetes API (`aws-vault` kubectl wrapper) | Your AWS profile via `aws-vault exec` | Read-only `kubectl` commands you submit (get, describe, logs, top, events, etc.); cluster context and namespace resolved from your local `service-registry.yaml` |
| Postgres (databases via `Dev10x:db-psql`) | Connection strings from `databases.yaml` (env or keyring) | Read-only SQL queries you submit; results returned locally |
| Anthropic API (Claude review CI) | Repository `ANTHROPIC_API_KEY` secret | PR diffs, commit metadata, and review comments processed by GitHub-hosted Claude actions |
| PyPI (release CI only) | Trusted-publisher OIDC | Plugin distribution artifacts |

Each integration is governed by the upstream vendor's own
privacy policy.
Review and configure these separately — the plugin neither
proxies nor caches third-party credentials.

## Your control over the data

Because everything is local, you can inspect or delete all
plugin data directly:

```bash
# Session state and task plans
rm -rf ~/.claude/projects/<project>/

# Per-project auto-memory
rm -rf ~/.claude/projects/<project>/memory/

# Global Dev10x config
rm -rf ~/.claude/memory/Dev10x/

# Hook audit logs
rm -rf /tmp/Dev10x/

# Per-project config and playbook overrides
rm -rf <your-repo>/.claude/Dev10x/
```

Disable audit logging entirely:

```bash
export DEV10X_HOOK_AUDIT=0
```

## Children

The plugin is a professional development tool and is not
directed at children under 13.

## Security disclosures

For security-related concerns, open a private security advisory
on the repository at
<https://github.com/Dev10x-Guru/dev10x-claude/security/advisories/new>.

## Changes to this policy

This policy is versioned with the repository.
Material changes will be announced in the `CHANGELOG.md` and
dated at the top of this file.

## Contact

Questions or concerns about this policy: open an issue at
<https://github.com/Dev10x-Guru/dev10x-claude/issues>.
