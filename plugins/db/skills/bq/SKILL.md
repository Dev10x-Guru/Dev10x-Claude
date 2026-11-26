---
name: dev10x-db:bq
description: >
  Read-only BigQuery access through MCP tools that wrap the bq CLI —
  so an agent can explore datasets and run a SELECT against
  project.dataset.table without a blanket `Bash(bq query:*)` allow that
  would also approve DELETE, MERGE or a --destination_table write.
  TRIGGER when: reading BigQuery data, listing BigQuery datasets or
  tables, or checking a BigQuery table's columns.
  DO NOT TRIGGER when: querying Postgres (use dev10x-db:db-psql), or the
  statement writes (print it for the user, see dev10x-db:sql-handoff).
user-invocable: true
invocation-name: dev10x-db:bq
allowed-tools:
  - mcp__plugin_dev10x_db__bq_query
  - mcp__plugin_dev10x_db__bq_datasets
  - mcp__plugin_dev10x_db__bq_tables
  - mcp__plugin_dev10x_db__bq_schema
---

# dev10x-db:bq

**Announce:** "Using dev10x-db:bq to read BigQuery through the read-only
tools."

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Run read-only BigQuery query", activeForm="Querying BigQuery")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Prerequisites

- The `bq` CLI from the Google Cloud SDK, on `PATH`.
- Credentials from `gcloud auth login` (and
  `gcloud auth application-default login` where your setup needs it).
- No `databases.yaml`, no DSN and no keyring entry.
  The tools use whatever account `gcloud` holds.

## Workflow: schema first

Never guess a column name.
Walk down from the project before writing a query:

1. **Datasets** — `mcp__plugin_dev10x_db__bq_datasets(project_id="<project>")`
2. **Tables** — `mcp__plugin_dev10x_db__bq_tables(dataset="<project>.<dataset>")`
3. **Columns** — `mcp__plugin_dev10x_db__bq_schema(table="<project>.<dataset>.<table>")`
4. **Estimate** a query that scans a large table first:
   `mcp__plugin_dev10x_db__bq_query(sql="SELECT …", dry_run=true)`.
   The `job` payload is bq's raw dry-run output; read the bytes it
   would process from there.
   **REQUIRED:** never pass `maximum_bytes_billed` above the 10 GiB
   default on your own.
   When the estimate exceeds it, stop, report the estimate, and let the
   user decide whether to narrow the query or raise the cap.
5. **Run** it: `mcp__plugin_dev10x_db__bq_query(sql="SELECT …")`.
   Read `truncated`; when it is true, add a `LIMIT`, a filter, or raise
   `max_rows` (1-10000).
   A page of exactly `max_rows` rows also reads as truncated.
   When bq prints something other than a row list, `rows` is empty and
   `raw` carries the output; read `raw` before calling the result empty.

Address every table in SQL as `` `project.dataset.table` ``.
Pass `project_id` to bill a project other than the gcloud default, and
`location` when the dataset lives outside the default location.

## Safety rules

The tool refuses before `bq` runs, so a refusal costs nothing:

1. **One SELECT or WITH statement only.**
   Multi-statement scripts, DML, DDL, `MERGE`, `EXPORT DATA`,
   `LOAD DATA`, `CALL` and `EXECUTE IMMEDIATE` are blocked, and so is
   `EXTERNAL_QUERY`, whose SQL hides in a string literal.
   Leave out the trailing `;`, do not start the SQL with `-` (bq would
   read it as a flag), and use plain `\n` line breaks: any `;`, a
   leading `-`, and `\r`, `\f` or `\v` are refused.
   BigQuery keywords such as `MERGE` or `CALL` are refused even inside a
   string literal or comment, and so is a run of four or more identical
   quotes; rephrase the literal (for example `CONCAT('ca', 'll')`).
   The rules are the same ones the DX004 hook applies to `bq query`
   (`dev10x.core.domain.rules.read_only_sql`).
2. **No hidden flags.**
   `~/.bigqueryrc`, `BIGQUERYRC` and `FLAGS_*` are not read, so they
   cannot add `--destination_table` or `--replace`.
3. **Cost cap.**
   `maximum_bytes_billed` defaults to 10 GiB and is capped at 1 TiB.
   A query over the cap fails in BigQuery without billing.
4. **Bounded wait.** The tool stops waiting for `bq` after 120 seconds.
   [Verify] whether the BigQuery job keeps running server-side; the
   byte cap still bounds what it can bill.

**REQUIRED: no fallback to raw `bq`.**
This covers every error from these tools: a refused statement, `bq`
missing from `PATH`, expired `gcloud` credentials, the timeout and the
byte cap.
Do not retry through Bash `bq`, a script or another tool.
Report the error; for credentials, tell the user to run
`gcloud auth login`.

### Handing off a refused write

1. Print the statement in a fenced `sql` block whose first line names
   the target:

   ```sql
   -- Run against: <project>.<dataset> (BigQuery)
   ```

2. One statement per block, with an exact `WHERE` clause and the row
   count you expect — the format of `dev10x-db:sql-handoff`.
   Its `databases.yaml` lookup and `db-psql` read-back do not apply to
   BigQuery.
3. Ask the user to run it in the BigQuery console or their own `bq`, and
   end the turn.
4. After the user says it ran, read the effect back with a `bq_query`
   SELECT on the same `WHERE` clause before building on it.

Keep the task open until that read-back is done.

## Move raw `bq` to deny

Once this skill is in use, raw `bq` no longer needs an allow rule.
`dev10x:plugin-doctor` reports `Bash(bq:*)`, `Bash(bq query:*)` and
similar allows (strategy `raw-bq-allow`).
Move them from `permissions.allow` to `permissions.deny` in your own
user settings; the plugin does not edit that file for you.

## Integration

- **`dev10x-db:sql-handoff`** — the handoff block format reused above.
- **`dev10x-db:db-psql`** — the Postgres sibling of this skill.
