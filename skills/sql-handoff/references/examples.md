# dev10x:sql-handoff Examples

Worked handoffs for `dev10x:sql-handoff`. Each one prints the SQL in
chat text first, asks a question that only refers to it, and
verifies with a SELECT before moving on.

## Example 1: Single UPDATE by primary key

The agent needs shop 4182 deactivated on backend staging.

**Agent (chat text):**

```sql
-- Run against: bs (backend-staging)
-- Expect: UPDATE 1
UPDATE shop SET is_active = false WHERE id = 4182;
```

**Agent (`AskUserQuestion`):** "Did you run the UPDATE above on bs?"

- Done, ran it (Recommended)
- Use a different row
- Didn't run it

**User:** Done, ran it.

**Agent (via `dev10x:db-psql`):**

```bash
${CLAUDE_PLUGIN_ROOT}/skills/db-psql/scripts/db.sh bs "SELECT id, is_active FROM shop WHERE id = 4182"
```

The read-back shows `is_active = f`, so the agent continues.

## Example 2: Ambiguous row — confirm first

The user asked to "close the duplicate Acme account". Two rows match
on name, so the agent runs a confirming SELECT before writing:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/db-psql/scripts/db.sh bs "SELECT id, name, created_at, is_active FROM account WHERE name = 'Acme Tires' ORDER BY created_at"
```

The result shows ids 311 (older, active orders) and 902 (created
yesterday, no orders). The agent names 902 as the duplicate, says
why, and hands off one statement keyed by id rather than by name:

```sql
-- Run against: bs (backend-staging)
-- Expect: UPDATE 1
UPDATE account SET is_active = false WHERE id = 902;
```

"Did you run the UPDATE above on bs?" with the same three options.
After "Done, ran it", the agent re-runs the confirming SELECT and
checks that 902 is inactive and 311 is unchanged.

## Example 3: "Use a different row"

Same handoff as Example 2, but the user answers **Use a different
row** and says the duplicate is 311. The agent does not edit the
earlier block. It runs a confirming SELECT for id 311, prints a
fresh block with `WHERE id = 311`, and asks again. The earlier block
stays in the transcript as a record of what was *not* run.

## Example 4: The hook blocked a write

The agent tried `db.sh bs "DELETE FROM cart_item WHERE cart_id = 77"`
and the PreToolUse hook rejected it. The agent does not retry with
`-c`, a temp file, or a wrapper script. It first counts the rows the
DELETE would remove:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/db-psql/scripts/db.sh bs "SELECT count(*) FROM cart_item WHERE cart_id = 77"
```

The count is 3, so the handoff states it:

```sql
-- Run against: bs (backend-staging)
-- Expect: DELETE 3
DELETE FROM cart_item WHERE cart_id = 77;
```

"Did you run the DELETE above on bs?" After "Done, ran it", the
agent re-runs the count and expects `0`.

## Anti-pattern: SQL inside the question

```
AskUserQuestion(question="Please run: UPDATE shop SET is_active = false WHERE id = 4182; — done?")
```

The copy from the widget carries the frame's `│` into psql and fails
with `syntax error at or near "│"`. There is also no
`-- Run against:` header, so nothing says which database the
statement belongs to.
