# Voice Narration Examples

Worked examples for `dev10x:voice-channel` Step 2. Each pair shows
the same board read aloud two ways.

## "What needs me?"

Board:

```
Needs you (1)
  payments migration [dev10x-7] — Keep the old refund endpoint? (4 min ago)
Working (2)
  login fix [dev10x-9] — Running the full test suite. (1 min ago)
  docs refresh [kb-3] — Writing the handbook page. (6 min ago)
Done (1)
  checkout copy [tt-2] — PR ready, CI green. (20 min ago)
```

❌ "Session dev10x-7 asks about PR 1588, ticket GH-1624 is running
tests in dev10x-9, kb-3 is on the handbook, and tt-2 finished PR 412
with green CI — should I merge it, and what about the refund
endpoint?"

✅ "One session needs you and two are working. The checkout copy is
done with green checks. Should the payments migration keep the old
refund endpoint?"

```
--- for the text session (do not read aloud) ---
payments migration = dev10x-7; checkout copy = tt-2, PR #412
```

## A finished task with a review

❌ "dev10x-9 pushed commit a3f9c1e to PR 1630; the diff touches
src/auth/session.py lines 40 to 88."

✅ "The login fix is done. Its code review waits for your screen."

The review itself goes to the `[screen]` list with the PR link.

## Several decisions at once

❌ "Should I merge the checkout copy, and should the payments migration
keep the old endpoint, and do you want the docs in Polish?"

✅ "Three decisions wait; the most urgent first. Should the payments
migration keep the old refund endpoint?"

The other two stay as `Decide:` tasks for the next turns.

## Naming

| Say | Do not say |
|-----|------------|
| the login fix | GH-1624, PR 1630, dev10x-9 |
| the payments migration | the session in worktree 7 |
| two sessions | sessions dev10x-7 and kb-3 |
| your review is waiting | review requested on #412 |

A callsign is two or three words for the work, set once and kept
across restarts (`dev10x:bus` § Registry).
