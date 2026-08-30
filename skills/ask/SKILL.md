---
name: Dev10x:ask
description: >
  Surface what is still open in a session and route it where it
  survives. Reformulate plain-text decision questions into
  AskUserQuestion widgets, sweep the session for open loops and
  sync them to the task list, or output a reinforcement nudge.
  TRIGGER when: supervisor sees a plain-text decision question that
  should have been an AskUserQuestion widget, wants recent prose
  questions converted into structured prompts, or asks what is
  still open / unanswered / outstanding in the session.
  DO NOT TRIGGER when: agent is already using AskUserQuestion
  correctly, or the question is purely informational (no decision).
user-invocable: true
invocation-name: Dev10x:ask
allowed-tools:
  - AskUserQuestion
  - TaskCreate
  - TaskUpdate
  - TaskList
  - Read(${CLAUDE_PLUGIN_ROOT}/.claude/rules/skill-gates.md)
  - Read(${CLAUDE_PLUGIN_ROOT}/.claude/rules/essentials.md)
---

# Dev10x:ask — Structured Decision Widgets

**Announce:** "Using Dev10x:ask to surface open decisions and
loops."

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Surface open decisions and loops", activeForm="Surfacing open loops")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Overview

Agents drift toward plain-text questions for supervisor decisions,
and toward letting other open items — promised follow-ups,
deferred decisions, unaddressed findings — scroll out of the
window. This skill provides three corrective modes:

- **Mode 1 — Reformulate** — scan recent turns, extract decision
  questions, present them as `AskUserQuestion` widgets
- **Mode 2 — Reinforce** — output a reinforcement message reminding
  the agent to use `AskUserQuestion` for all decision points
- **Mode 3 — Open loops** — sweep the session for four loop shapes
  and sync each to the task list so it outlives the exchange

## Mode Detection

Determine the mode from arguments and context:

| Signal | Mode |
|--------|------|
| No arguments, recent plain-text questions visible | Reformulate |
| Argument is a quoted question string | Reformulate (single question) |
| User says "ask that again" or "convert that to options" | Reformulate |
| Argument `--loops` or `loops` | Open loops |
| User says "open loops", "what's still open", "anything unanswered", "loose ends" | Open loops |
| Argument `--reinforce` or `reinforce` | Reinforce |

If ambiguous, default to **Reformulate** — it is the more
common use case.

## Mode 1: Reformulate

Scan the last 10-15 turns for plain-text questions that ask the
supervisor to choose, decide, or approve, and that have not been
answered (Step 1); rephrase each into a header, question, and
2-4 labelled options (Step 2); present them (Step 3); report what
was converted and what was skipped (Step 4).

**Step 3 — REQUIRED: Call `AskUserQuestion`** (do NOT use plain
text). Present all extracted questions in a single
`AskUserQuestion` call (up to 4 questions per call). If more than
4 questions were found, batch them into sequential calls.

See [`references/reformulate-mode.md`](references/reformulate-mode.md)
for the full scan criteria, the option-structuring rules, the
Step 4 summary contents, and the list of question types that must
NOT be reformulated (clarifying information, free-text input,
confirmations without alternatives, optional preferences).

## Mode 2: Reinforce

### Step 1: Identify the violation

Scan recent conversation for the plain-text question that
triggered this invocation. If the user provided arguments
(e.g., `/Dev10x:ask reinforce`), use the most recent
plain-text decision question as the target.

### Step 2: Read the rules

Read the decision gate rules from:
- `.claude/rules/skill-gates.md` — pattern and checklist
- `.claude/rules/essentials.md` § Decision Gates — global scope

### Step 3: Output reinforcement

Emit the structured message in
[`references/reinforcement-message.md`](references/reinforcement-message.md),
substituting the offending question. Mode 2 opens no gate — do
NOT call `AskUserQuestion` while emitting it.

## Mode 3: Open Loops

Mode 1 only sees questions and only produces widgets, so a loop
the supervisor dismisses — or one that was never question-shaped
to begin with — is dropped without a trace. This mode detects
loops of every shape and lands them on the task list, which is
the only session artifact that survives the exchange.

### Step 1: Sweep the session for open loops

Scan the session for these four shapes. A loop is **open** when
nothing in the session closed it — not when it merely looks
unfinished.

| Shape | Signal | Closed by |
|-------|--------|-----------|
| Unanswered supervisor question | Supervisor asked; no answer followed | An answer in a later turn |
| Un-actioned agent commitment | "I'll do X", "next I'll Y", "we should follow up with Z" | The action visibly happening |
| Deferred / batched decision | Queued in task metadata per the Batched Decision Queue, or "let's decide later" | Being presented and answered |
| Surfaced-but-unaddressed finding | A review finding, failing check, or warning that was reported | A fix, a ticket, or explicit dismissal |

Do NOT report a loop the supervisor explicitly declined
("skip that", "not now"). A declined loop is closed.

### Step 2: Reconcile against the task list

**REQUIRED: Call `TaskList` once** before writing anything — the
skill must not create a task that duplicates existing coverage.

For each detected loop:

- **No corresponding task** → `TaskCreate` with a subject naming
  the loop and a description carrying enough context to act on it
  cold. Insert it before any terminal `Verify AC` task so the
  empty-task-list invariant (`essentials.md` § Task List
  Invariant) still holds.
- **A corresponding task exists** → `TaskUpdate` that task,
  recording the loop in `metadata.open_loop` rather than creating
  a duplicate.

Task-list sync happens for **every** loop shape, including
decision-shaped ones. The widget in Step 3 is how a decision gets
answered now; the task is how it survives if it does not.

### Step 3: Batch the decision-shaped loops

Loops of the *deferred decision* shape — and unanswered
supervisor questions that ask for a choice — additionally flow
into Mode 1 Step 3's batching: **REQUIRED: Call
`AskUserQuestion`** with up to 4 per call, sequential calls
beyond that.

Non-decision loops (commitments, findings) become tasks only.
They have no alternatives to choose between, so a widget would
manufacture a decision that does not exist.

**When no loops are detected, call nothing** — no `TaskCreate`,
no `AskUserQuestion`. Report "no open loops detected" and stop.

### Step 4: Report results

Output a summary naming, for each loop: its shape, whether it
became a new task or annotated an existing one, and whether it
was presented as a widget. Naming the shape lets the supervisor
spot a false positive without re-reading the session.

## Examples

See [`references/examples.md`](references/examples.md) for
walkthroughs covering reformulation, the reinforcement nudge, a
quoted question, a four-shape open-loop sweep, and the
no-loops-found case.

## Integration

This skill can be referenced by other skills as a
reinforcement mechanism:

- **`Dev10x:diag-friction`** — handles CLI-to-skill
  redirects and permission-friction diagnosis; `Dev10x:ask`
  handles plain-text-to-widget redirects
- **`Dev10x:work-on`** — can invoke `Dev10x:ask reinforce` if
  an agent within the work-on pipeline uses plain text for a
  decision point, or `Dev10x:ask --loops` before the Verify-AC
  gate to catch loops that never reached the task list
- **`Dev10x:session-wrap-up`** — run `--loops` first so nothing
  open is lost at session close
- **Skill authors** — reference this skill in SKILL.md when
  documenting decision gates as a fallback enforcement mechanism
