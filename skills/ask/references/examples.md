# Dev10x:ask — Examples

Walkthroughs for each mode. See `SKILL.md` for the mode-detection
table and the orchestration contract.

## Example 1: Reformulate a recent question

**Context:** Agent previously asked in plain text:
"Should I fix this with a retry wrapper or by increasing the
timeout? The retry approach is more resilient but adds complexity."

**Invocation:** `/Dev10x:ask`

**Result:** Calls `AskUserQuestion` with:
```
question: "How should we fix the timeout failure?"
header: "Fix strategy"
options:
  - label: "Retry wrapper (Recommended)"
    description: "More resilient, adds wrapper complexity"
  - label: "Increase timeout"
    description: "Simpler change, less resilient to transient failures"
```

## Example 2: Reinforce the convention

**Invocation:** `/Dev10x:ask reinforce`

**Result:** Outputs the reinforcement message from
[`reinforcement-message.md`](reinforcement-message.md), citing the
specific rules and correct pattern.

## Example 3: Convert a quoted question

**Invocation:** `/Dev10x:ask "Should we use polling or webhooks?"`

**Result:** Calls `AskUserQuestion` with:
```
question: "Should we use polling or webhooks?"
header: "Strategy"
options:
  - label: "Polling"
    description: "Simpler to implement, higher latency"
  - label: "Webhooks"
    description: "Real-time updates, requires endpoint setup"
```

## Example 4: Open loops across four shapes

**Context:** A long session in which:

1. The supervisor asked "does the migration need a backfill?" —
   never answered.
2. The agent said "I'll add a regression test once the fix lands"
   — the fix landed three turns ago, no test exists.
3. A `git-groom` strategy decision was queued in task metadata
   under the Batched Decision Queue pattern and never presented.
4. `Dev10x:review` surfaced an N+1 query in `quotes/service.py`
   that was noted and then scrolled past.

**Invocation:** `/Dev10x:ask --loops`

**Result:** One `TaskList` call to find existing coverage, then:

- Loop 2 (commitment) and loop 4 (finding) have no corresponding
  task → one `TaskCreate` each, inserted before the terminal
  Verify-AC task.
- Loop 1 (supervisor question) already has a related open task →
  `TaskUpdate` annotates it via `metadata.open_loop` rather than
  creating a duplicate.
- Loops 1 and 3 are decision-shaped → both are carried into a
  single `AskUserQuestion` call (2 questions, under the batch
  limit of 4). Loops 2 and 4 are not decisions, so they become
  tasks only.

**Step 4 summary** reports 4 loops detected, 2 tasks created, 1
task annotated, 2 questions presented, and names the shape of
each loop so the supervisor can spot a false positive.

## Example 5: No open loops found

**Invocation:** `/Dev10x:ask --loops` in a session where every
question was answered and every commitment was executed.

**Result:** No `TaskCreate`, no `TaskUpdate`, and — importantly —
no `AskUserQuestion`. The skill reports "no open loops detected"
and stops. Manufacturing a decision to justify the invocation is
the failure mode this example pins.
