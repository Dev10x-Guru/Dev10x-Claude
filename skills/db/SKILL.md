---
name: Dev10x:db
invocation-name: Dev10x:db
description: >
  Safe database query planning for Claude Code. When querying any
  database, ensures schema-first construction and read-only safety
  so queries are accurate and never modify production data.
  TRIGGER when: code needs database queries, schema discovery, or
  SQL construction.
  DO NOT TRIGGER when: no database interaction needed, or user is
  writing application code that happens to mention SQL in comments.
user-invocable: false
---

# Database Query Planning

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Create a task at invocation, mark completed when done:

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Plan database query", activeForm="Planning query")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

Schema-first query construction for safe, accurate database queries.

## Query Planning Workflow

Before writing any SQL:

1. **Load schema context** — search for schema memory files and
   project-specific db skills (see Context Discovery below)
2. **Verify table and column names** — never guess; cross-reference
   the schema files or run an `information_schema` query
3. **Write the query** — use verified names only
4. **Execute via engine-specific skill** — delegate to the appropriate
   execution layer (e.g., `Dev10x:db-psql` for PostgreSQL)

## Context Discovery Convention

Generic skills discover database context by searching these
resources (in order, first match wins per resource type):

### Schema files

1. `~/.claude/memory/Dev10x/db-*-schema.md` — global schema docs
   (preferred, see `references/config-resolution.md`)

### Database configuration

Handled by `Dev10x:db-psql` — see its SKILL.md for the full
search order. Key locations:

1. `$DB_CONFIG` environment variable (explicit override)
2. Plugin skill directory (`skills/db-psql/databases.yaml`)
3. `~/.config/Dev10x/databases.yaml` — XDG; preferred global location
4. `~/.claude/memory/Dev10x/databases.yaml` — deprecated fallback
5. Sibling plugin skills (`skills/*/databases.yaml`)
6. User skill directories (`~/.claude/skills/*/databases.yaml`)
7. Marketplace plugins (`~/.claude/plugins/marketplaces/*/skills/*/databases.yaml`)

### Additional context

- **Project db skills**: any skill matching `*:db` pattern (e.g.,
  `tt:db`, `acme:db`) — project-specific aliases, common queries,
  and DSN configuration
- **CLAUDE.md database sections**: database connection info or
  references in project instructions

Always load available context before constructing queries.

## Safety Rules

1. **Read-only queries only** — SELECT, WITH (CTEs), EXPLAIN, and SHOW
   are allowed. Never run INSERT, UPDATE, DELETE, DROP, ALTER, CREATE,
   TRUNCATE, or other write operations through automated tools
2. **Write queries**: print the raw SQL and tell the user to run
   it manually. Never attempt workarounds or bypass safety checks
3. **Use timeouts** — all queries should have statement timeouts to
   prevent runaway execution
4. **Limit large result sets** — use LIMIT on exploratory queries;
   never `SELECT *` on production tables without a WHERE clause

## Anti-Patterns

| Anti-Pattern | What to Do Instead |
|---|---|
| Guess table/column names | Load schema files first, or query `information_schema.tables` / `information_schema.columns` |
| Retry with random name variations | Stop and look up the correct name in schema docs |
| `SELECT *` on large tables | Use specific columns and LIMIT |
| Inline DSN strings in prompts | Use the engine-specific skill's wrapper script |
| Skip schema check for "simple" queries | Always verify — even common tables have gotchas |

## Schema Memory File Format

Schema files should follow this template. Place them at
`~/.claude/memory/Dev10x/db-<name>-schema.md` (preferred global
path per `references/config-resolution.md`):

```markdown
# <Project> Database Schema — <database-name>

## <Domain Group>

| Table | Key Columns | Notes |
|-------|-------------|-------|
| `table_name` | id, name, status, foreign_key_id | Brief purpose |

## Common Gotchas

- Table `actual_name` (NOT `guessed_name`)
- Money fields store JSON: `field::jsonb->>'amount'`

## Common Queries

### Find X by Y
\```sql
SELECT ... FROM ... WHERE ...
\```
```

## Integration

This skill provides query planning guidance. Actual query execution
is handled by engine-specific skills:

- **`Dev10x:db-psql`** — PostgreSQL via psql wrapper
