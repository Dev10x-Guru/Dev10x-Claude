---
name: dev10x:sql-handoff
description: >
  Use when a write (UPDATE, INSERT, DELETE, DDL) must reach a database
  the agent can only read through dev10x:db-psql — so the supervisor
  gets one paste-safe statement aimed at the right database, and the
  agent proves the effect before building on it.
  TRIGGER when: the agent needs the user to run non-SELECT SQL by hand,
  or the db-psql hook just blocked a write.
  DO NOT TRIGGER when: the SQL is a SELECT (run it via dev10x:db-psql),
  or the change belongs in a migration file in the codebase.
user-invocable: true
invocation-name: dev10x:sql-handoff
allowed-tools:
  - AskUserQuestion
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/db-psql/scripts/db.sh:*)
---

# dev10x:sql-handoff

**Announce:** "Using dev10x:sql-handoff to hand the write to you and
verify it afterwards."

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Hand off SQL write to supervisor", activeForm="Handing off SQL")`

Mark completed only after Step 5 verifies the write:
`TaskUpdate(taskId, status="completed")`

## Overview

The agent may run SELECTs through `dev10x:db-psql`; every write goes
through the supervisor's own psql session. The handoff is where a
write goes wrong: the wrong database, a stale WHERE clause, a
statement mangled in the copy-paste, or an agent that assumes "done"
means "worked". The five rules below close each of those gaps. One
handoff carries exactly one statement.

## The Rules

1. **Never put SQL inside an `AskUserQuestion` prompt.** The widget
   renders with box-drawing characters, and copying out of it
   carries them into psql (see Gotchas). Print the SQL first, in
   plain chat text, as a fenced `sql` block whose **first line** is
   the target header:

   ```sql
   -- Run against: <alias> (<label>)
   ```

   Then ask with `AskUserQuestion` — a question that only *refers*
   to the block above, never one that contains it.
2. **Verify with a SELECT after the user says it ran.** Run a
   read-back through `dev10x:db-psql` before continuing. Never trust
   the paste, a pasted psql output, or "done" on its own.
3. **One statement per handoff.** State the exact WHERE clause and
   the expected row count (`-- Expect: UPDATE 1`) inside the block.
   A second write waits for the first one's verification.
4. **Confirm the target first when the row is ambiguous.** If more
   than one row could match, or the agent picked the row from
   inference rather than a primary key, run (or hand over) a SELECT
   with the same WHERE clause first, and only write once it returns
   exactly the expected rows.
5. **Never bypass the read-only hook or wrap writes in scripts.** No
   `psql -c`, no `-f /tmp/fix.sql` through `db.sh`, no Python or
   shell wrapper that opens a connection, no `BEGIN; ... COMMIT;`
   smuggled into a SELECT. The hook block is the signal to hand off,
   not an obstacle to route around.

## Workflow

### Step 1: Pin the target

Resolve the alias and label from `databases.yaml`
(`db.sh --list`). Build the WHERE clause from a primary key
whenever one is known. If the target is ambiguous, apply Rule 4
before Step 2.

### Step 2: Print the statement

In plain chat text, not inside a tool call:

````markdown
```sql
-- Run against: bs (backend-staging)
-- Expect: UPDATE 1
UPDATE shop SET is_active = false WHERE id = 4182;
```
````

The block holds the header, the expected count, and one statement
— nothing else for the user to trim.

### Step 3: Ask about the block

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text). The
question names the statement and the alias but holds no SQL, e.g.
"Did you run the UPDATE above on bs?". Options:

- Done, ran it (Recommended) — psql reported the expected count
- Use a different row — the target is wrong; re-pin it
- Didn't run it — stop; leave the database unchanged

The agent cannot see the psql session, so the question says so
(`skill-gates.md` § state): "…on bs? I can't see your session — the
read-back will confirm."

### Step 4: Branch on the answer

- **Done, ran it** → Step 5.
- **Use a different row** → back to Step 1 with the user's
  correction; issue a fresh block (never edit the old one in place).
- **Didn't run it** → record that the write is outstanding and
  stop; do not continue as if it landed.

### Step 5: Verify

Run a read-back through `dev10x:db-psql` that selects the changed
columns with the same WHERE clause. Compare against the intended
end state. A mismatch is a finding to report, never something to
"fix" with another write in the same breath — go back to Step 1.

## Gotchas

**Box-drawing characters break the paste.** The `AskUserQuestion`
widget draws its prompt inside a frame. A statement embedded in the
question arrives in the clipboard with the frame attached:

```
│ UPDATE shop SET is_active = false WHERE id = 4182; │
```

psql rejects it:

```
ERROR:  syntax error at or near "│"
LINE 1: │ UPDATE shop SET is_active = false WHERE id = 4182; │
        ^
```

The user then hand-cleans the line, and hand-cleaning is exactly
where a WHERE clause gets truncated. Keep the SQL in a fenced block
in chat text (Rule 1); the question only points at it.

**A missing header sends the write to the wrong database.** Several
psql sessions are usually open at once. Without
`-- Run against: <alias> (<label>)` on the first line, nothing in
the block says which one it belongs to.

**"Done" is not evidence.** The user may have hit the wrong session,
an open transaction may never have committed, or a trigger may have
rewritten the row. Only the Step 5 read-back is evidence.

## Examples

See [`references/examples.md`](references/examples.md) for a single
UPDATE, an ambiguous-row handoff with a confirming SELECT first, a
"Use a different row" correction, and a hook-blocked write.

## Integration

- **`dev10x:db`** — plans the query and verifies table and column
  names before the handoff
- **`dev10x:db-psql`** — runs the confirming and verifying SELECTs;
  its "When a Query Is Blocked" section hands off to this skill
