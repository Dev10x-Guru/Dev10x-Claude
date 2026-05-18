---
name: Dev10x:skill-audit-queue
description: >
  Queue a skill-audit invocation for later by appending a tracker task
  to the end of the current task list. Use mid-session when you notice
  friction but do not want to interrupt in-flight work — the audit
  runs when the supervisor reaches the queued task.
  TRIGGER when: friction noticed mid-session, but interrupting current
  work is not desirable; supervisor wants the audit deferred until
  the active task completes.
  DO NOT TRIGGER when: supervisor wants the audit to run NOW (use
  Dev10x:skill-audit directly), or no friction has been observed.
user-invocable: true
invocation-name: Dev10x:skill-audit-queue
allowed-tools:
  - TaskCreate
  - TaskList
---

# Skill Audit Queue

Append a tracker task that defers a `Dev10x:skill-audit` invocation
to the end of the current task list. The audit itself does not run
here — only the TODO is recorded. When the supervisor reaches the
queued task, they invoke `Dev10x:skill-audit` directly to run the
diagnosis.

## Why this exists

`Dev10x:skill-audit` used to self-append a "cycle-audit" task as
its Step 0a (GH-148), but that coupled deferral semantics to the
audit invocation itself: the audit task only appeared when the
supervisor was ready to run it *now*, which made mid-session
deferral awkward and created an "audit pauses prior work" anti-
pattern (issue GH-219).

This skill separates the two concerns:

- **Defer the audit** → `Dev10x:skill-audit-queue` (this skill).
  Records intent. Does not interrupt current work.
- **Run the audit** → `Dev10x:skill-audit`. Executes the actual
  diagnosis when the supervisor is ready.

## Orchestration

This skill is a single-shot append. There are no phases.

**REQUIRED: Create one task at invocation.** Execute at startup:

1. `TaskCreate(subject="Run Dev10x:skill-audit-queue append", activeForm="Queueing audit")`

Mark `completed` after the audit task is appended.

## Workflow

### Step 1: Read current task list

Call `TaskList` to see existing tasks. Use this to locate the
correct insertion point.

### Step 2: Determine the insertion position

The audit task is appended at the **end** of the open task list,
with one exception: if a `Verify acceptance criteria` (or
`Verify AC`) task exists as the terminal task per the Task List
Invariant (`.claude/rules/essentials.md` § Task List Invariant
GH-149), insert the audit task **immediately before** it. The
verify-AC task must remain last.

No dependency wiring on the new task — it is independent of the
in-flight work.

### Step 3: Append the audit task

Build the task description from arguments (if any) or from a
short generic frame:

```
TaskCreate(
    subject="Invoke Dev10x:skill-audit to diagnose recent friction",
    description="Supervisor queued a skill audit during session. "
                "<frame from args or 'Investigate recent skill compliance gaps.'> "
                "When ready, invoke /Dev10x:skill-audit.",
    activeForm="Auditing skill usage"
)
```

If the supervisor passed free-text arguments (e.g.,
`/Dev10x:skill-audit-queue retry logic kept stalling`), use that
text as the frame.

### Step 4: Confirm

Print one line:

```
Queued Dev10x:skill-audit at end of task list. The audit will
not run until you reach the task and invoke /Dev10x:skill-audit.
```

Mark this skill's own startup task `completed`.

## Examples

### Example 1: Free-text frame

**Invocation:** `/Dev10x:skill-audit-queue git-commit kept asking redundant questions`

**Result:** A new task is appended (before Verify AC if present):
- subject: "Invoke Dev10x:skill-audit to diagnose recent friction"
- description: "Supervisor queued a skill audit during session.
  Frame: git-commit kept asking redundant questions. When ready,
  invoke /Dev10x:skill-audit."

### Example 2: No arguments

**Invocation:** `/Dev10x:skill-audit-queue`

**Result:** A new task is appended with a generic frame:
- description: "Supervisor queued a skill audit during session.
  Investigate recent skill compliance gaps. When ready, invoke
  /Dev10x:skill-audit."

## Related Skills

- `Dev10x:skill-audit` — runs the actual audit; invoke this from
  the queued task when ready
- `Dev10x:park` — generic deferral router; this skill is the
  specific audit-deferral path
