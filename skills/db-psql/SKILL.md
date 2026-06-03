---
name: Dev10x:db-psql
description: >
  Safe read-only psql wrapper for Claude Code. Provides db.sh with
  SQL validation hook so database queries are safe and auditable.
  Configure databases in databases.yaml with env var or keyring backends.
  TRIGGER when: executing SQL against configured databases.
  DO NOT TRIGGER when: planning queries (use Dev10x:db), or working
  with non-database tasks.
user-invocable: true
invocation-name: Dev10x:db-psql
allowed-tools:
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/db-psql/scripts/db.sh:*)
---

<!--
GH-127 #1 — `${CLAUDE_PLUGIN_ROOT}` is expanded by Claude Code at
runtime to the resolved cache path. User settings that pin the
absolute path (`/home/<user>/.claude/plugins/cache/.../db.sh:*`)
or omit the tilde will not match this rule. Run
`Dev10x:plugin-maintenance` (mode: full) or
`Dev10x:upgrade-cleanup` to canonicalize pinned/absolute paths in
`settings.local.json` to the `~/.claude/plugins/cache/.../**/`
wildcard form, which matches across plugin version bumps. The
canonicalization is implemented in
`src/dev10x/skills/permission/doctor.py::canonicalize_rule`.
-->


# PostgreSQL Query Execution

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Create a task at invocation, mark completed when done:

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Execute safe database query", activeForm="Querying database")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

Safe read-only psql wrapper with two layers of protection:

1. **PreToolUse hook** (`hooks/scripts/validate-sql.py`) — blocks
   non-SELECT queries before they reach psql
2. **Connection-level safety** — `SET default_transaction_read_only = on`
   and read-only DB users / read-replica endpoints

## How to Use

```bash
${CLAUDE_PLUGIN_ROOT}/skills/db-psql/scripts/db.sh <database> "<SQL>"
${CLAUDE_PLUGIN_ROOT}/skills/db-psql/scripts/db.sh <database> -f <file>
${CLAUDE_PLUGIN_ROOT}/skills/db-psql/scripts/db.sh --list
```

## Common Mistakes (DO NOT do these)

```bash
# WRONG — -c flag is not supported, triggers safety hook block
db.sh pp -c "SELECT ..."

# WRONG — stdin piping is not supported
echo "SELECT ..." | db.sh pp

# CORRECT — SQL as second positional argument in quotes
db.sh pp "SELECT ..."
```

## Setup

### 0. Prerequisites

- `psql` (PostgreSQL client)
- `uv` -- Python package manager used by `parse-databases.py`
  (`pip install uv` or `brew install uv`)
- `secret-tool` (libsecret-tools) -- only needed for `keyring` backend

### 1. Configure databases

Create `databases.yaml` in one of the discovered locations. The
db.sh script searches for config files in this order:

1. `$DB_CONFIG` environment variable (explicit path)
2. Own skill directory (`skills/db-psql/databases.yaml`)
3. `~/.config/Dev10x/databases.yaml` (XDG; preferred global location)
4. `~/.claude/memory/Dev10x/databases.yaml` (deprecated fallback)
5. Sibling plugin skill directories (`skills/*/databases.yaml`)
6. User skill directories (`~/.claude/skills/*/databases.yaml`)
7. Marketplace plugins (`~/.claude/plugins/marketplaces/*/skills/*/databases.yaml`)

Example YAML with both backends:

```yaml
databases:
  my-prod:
    label: "My App production (read-only)"
    aliases: [mp]
    backend: env
    env_var: DB_MY_PRODUCTION_RO

  my-staging:
    label: "My App staging (read-only)"
    aliases: [ms]
    backend: keyring
    keyring_service: claude-db
    keyring_account: my-staging
```

### 2. Set DSN

Configure the connection string using the backend specified in
`databases.yaml`:

**env backend** — set the environment variable in your shell profile:

```bash
export DB_MY_PRODUCTION_RO="postgres://user:pass@host:5432/db"
```

**keyring backend** — store the DSN in the system keyring:

```bash
secret-tool store --label "claude-db my-staging" \
  service claude-db account my-staging
```

### 3. Safety hook (auto-registered)

The SQL validation hook (`validate-sql.py`) is automatically
registered via `hooks/hooks.json` when this plugin is installed.
No manual configuration needed.

## Safety Rules

1. **Read-only queries only** — SELECT, WITH (CTEs), EXPLAIN, and SHOW
   are allowed. The hook rejects INSERT, UPDATE, DELETE, DROP, ALTER,
   CREATE, TRUNCATE, and other write operations
2. **Read-only connections** — DSNs should use read-only DB users or
   read-replica endpoints
3. **30-second timeout** — prevents runaway queries
4. **Non-SELECT queries**: print the raw SQL and tell the user to run
   it manually. Never attempt workarounds.

## When a Query Is Blocked

If the PreToolUse hook blocks a non-SELECT query, tell the user:

> This query modifies data and cannot be run through the read-only
> tool. Here's the SQL to run manually:
>
> ```sql
> -- Run against: <alias> (<label>)
> <the blocked query>
> ```

**REQUIRED: Always prefix SQL snippets with a target database
comment** when outputting SQL for manual execution. This prevents
copy-paste errors where SQL intended for staging runs against
production. The comment format is:
```sql
-- Run against: bs (backend-staging)
```

Never attempt to bypass the safety checks.

## Integration

- Uses **`Dev10x:db`** for query planning and schema discovery
- Project-specific skills (e.g., `tt:db`) provide `databases.yaml`
  with aliases and schema references
