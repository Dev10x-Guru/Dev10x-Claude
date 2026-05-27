---
name: Dev10x:jira
description: Use when querying, linking, or fetching JIRA issues — so credentials, hook-safe curl patterns, and hierarchy gotchas are always at hand
user-invocable: false
allowed-tools:
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/jira/scripts/:*)
---

**Announce:** "Using Dev10x:jira to [purpose]."

## Prerequisites

Set the `JIRA_TENANT` env var to your Atlassian tenant name
(e.g., `mycompany` for `mycompany.atlassian.net`). All scripts
require it — there is no default.

Store credentials in the system keyring:
```bash
secret-tool store --label "JIRA email" service jira key email
secret-tool store --label "JIRA API token" service jira key api_token
```

## Scripts

All scripts live in `${CLAUDE_PLUGIN_ROOT}/skills/jira/scripts/` and are
pre-approved via `allowed-tools`.

| Script | Purpose | Example |
|--------|---------|---------|
| `jira-get.sh` | Fetch issue by key | `jira-get.sh PROJ-100` |
| `jira-search.sh` | Search by JQL | `jira-search.sh "text ~ 'wheel nut'"` |
| `jira-link.sh` | Link two issues | `jira-link.sh PROJ-100 "Blocks" PROJ-200` |
| `jira-link-types.sh` | List available link types | `jira-link-types.sh` |
| `jira-update.sh` | Update issue from JSON file | `jira-update.sh PROJ-100 /tmp/payload.json` |
| `jira-comment.sh` | Add a comment from a file | `jira-comment.sh PROJ-100 /tmp/body.md` |

## Tenant Wrapper Pattern

A tenant wrapper skill (e.g. `acme:jira`) binds a fixed
`JIRA_TENANT` and delegates here. **Do NOT bind the tenant with a
command-line env prefix:**

```bash
# ❌ Anti-pattern — env prefix shifts the allow-rule prefix
JIRA_TENANT=acme ${CLAUDE_PLUGIN_ROOT}/skills/jira/scripts/jira-get.sh PROJ-1
```

The leading `JIRA_TENANT=acme` shifts the effective Bash command
prefix, so **no** `Bash(.../scripts/jira-get.sh:*)` allow rule can
ever match — every call hits the permission gate. This is the same
prefix-shift class as the global "No env-var prefix on git" rule.

**Instead, ship a wrapper script** that binds the tenant *inside* the
command, so the wrapper's own path is what the allow rule matches:

```bash
# ✅ Wrapper script — tenant binding inside, one allow rule, no friction
~/.claude/skills/acme:jira/scripts/jira-get.sh PROJ-1
```

A copy-paste starting point lives at
[`templates/jira-wrap.sh.example`](templates/jira-wrap.sh.example).
Each thin wrapper `export JIRA_TENANT=<tenant>` then `exec`s the
matching base script. Pre-approve the wrapper directory with one rule:

```json
"Bash(~/.claude/skills/acme:jira/scripts/:*)"
```

This keeps the tenant binding inside the skill (not scattered across
user settings) and covers every base op — get, search, link, update,
comment — without a per-script allow rule or an env-var prefix.

The alternative — setting `JIRA_TENANT` in `~/.claude/settings.json`
under `env:` — also removes the prefix, but binds a single tenant for
the whole session and so cannot serve multiple tenants. Prefer the
wrapper-script approach.

## Hook Safety

The PreToolUse hook **blocks `for` loops** in Bash commands. Always call scripts individually — one call per Bash tool use.

```bash
# ❌ Blocked by hook
for payload in '...' '...'; do curl ...; done

# ✅ Separate tool calls
${CLAUDE_PLUGIN_ROOT}/skills/jira/scripts/jira-link.sh PROJ-100 "1-Relates" PROJ-200
${CLAUDE_PLUGIN_ROOT}/skills/jira/scripts/jira-link.sh PROJ-100 "1-Relates" PROJ-300
```

## JIRA Hierarchy Gotcha

**Task → Task parent assignment fails** with: `"Given parent work item does not belong to appropriate hierarchy."`

Tasks can only be children of Epics. Use **issue links** instead for same-level relationships:

| Need | Use |
|------|-----|
| Group related tasks | `1-Relates` link |
| Sequence work | `Blocks` link (`inward` blocks `outward`) |
| True parent/child | Create an Epic and use the `parent` field |

## Common Operations

### Fetch an issue
```bash
${CLAUDE_PLUGIN_ROOT}/skills/jira/scripts/jira-get.sh PROJ-100
```

### Search issues
```bash
${CLAUDE_PLUGIN_ROOT}/skills/jira/scripts/jira-search.sh "text ~ 'search term' ORDER BY created DESC"
```

### Link tickets (inward [type] outward)
```bash
${CLAUDE_PLUGIN_ROOT}/skills/jira/scripts/jira-link.sh PROJ-100 "1-Relates" PROJ-200
${CLAUDE_PLUGIN_ROOT}/skills/jira/scripts/jira-link.sh PROJ-100 "Blocks" PROJ-200
```
HTTP 201 = success.

### Update an issue from JSON payload
```bash
# Write ADF payload to a file first, then update
${CLAUDE_PLUGIN_ROOT}/skills/jira/scripts/jira-update.sh PROJ-100 /tmp/claude/jira-payload.json
```
HTTP 204 = success.

### Add a comment from a file
```bash
${CLAUDE_PLUGIN_ROOT}/skills/jira/scripts/jira-comment.sh PROJ-100 /tmp/claude/comment-body.md
```

### List link types
```bash
${CLAUDE_PLUGIN_ROOT}/skills/jira/scripts/jira-link-types.sh
```
