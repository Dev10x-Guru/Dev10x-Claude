---
name: Dev10x:ask
description: >
  Reformulate plain-text questions into structured AskUserQuestion
  widgets and reinforce the decision-gate convention. Two modes:
  reformulate recent questions into clickable options, or output a
  reinforcement nudge when an agent asks plain-text decisions.
  TRIGGER when: supervisor sees a plain-text decision question that
  should have been an AskUserQuestion widget, or wants to convert
  recent prose questions into structured prompts.
  DO NOT TRIGGER when: agent is already using AskUserQuestion
  correctly, or the question is purely informational (no decision).
user-invocable: true
invocation-name: Dev10x:ask
allowed-tools:
  - AskUserQuestion
  - Read(${CLAUDE_PLUGIN_ROOT}/.claude/rules/skill-gates.md)
  - Read(${CLAUDE_PLUGIN_ROOT}/.claude/rules/essentials.md)
---

# Dev10x:ask — Structured Decision Widgets

**Announce:** "Using Dev10x:ask to convert questions into
structured decision widgets."

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Create a task at invocation, mark completed when done:

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Convert questions to widgets", activeForm="Converting questions")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Overview

Agents drift toward plain-text questions for supervisor decisions.
This skill provides two corrective modes:

- **Reformulate** — scan recent turns, extract decision questions,
  present them as `AskUserQuestion` widgets
- **Reinforce** — output a reinforcement message reminding the
  agent to use `AskUserQuestion` for all decision points

## Mode Detection

Determine the mode from arguments and context:

| Signal | Mode |
|--------|------|
| No arguments, recent plain-text questions visible | Reformulate |
| Argument `--reinforce` or `reinforce` | Reinforce |
| Argument is a quoted question string | Reformulate (single question) |
| User says "ask that again" or "convert that to options" | Reformulate |

If ambiguous, default to **Reformulate** — it is the more
common use case.

## Mode 1: Reformulate

### Step 1: Scan recent conversation

Look back through the most recent 10-15 conversation turns for
plain-text questions directed at the supervisor. A question
qualifies for reformulation when ALL of these are true:

1. It asks the supervisor to **choose** between alternatives,
   **decide** on an approach, or **approve/reject** something
2. It was asked as plain text (not via `AskUserQuestion`)
3. It has not already been answered by the supervisor

Skip questions that are purely informational (e.g., "What's the
file path?", "Can you clarify the requirement?").

### Step 2: Extract and structure each question

For each qualifying question, build a structured representation:

- **Header**: 1-3 word topic label (max 12 chars)
- **Question**: the decision being asked, rephrased as a clear
  question ending with `?`
- **Options**: 2-4 discrete choices extracted from the question
  context. Each option needs:
  - `label`: concise choice name (1-5 words)
  - `description`: what happens if chosen, trade-offs
- **Recommended**: if context suggests a default, mark it with
  "(Recommended)" suffix on the label and place it first

### Step 3: Present reformulated widgets

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
Present all extracted questions in a single `AskUserQuestion`
call (up to 4 questions per call). If more than 4 questions
were found, batch them into sequential calls.

### Step 4: Report results

After the supervisor responds, output a brief summary:
- How many questions were reformulated
- The supervisor's choices
- Any questions that were skipped (with reason)

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

Output a structured reinforcement message:

```
## Decision Gate Reinforcement

**Violation detected:** Plain-text decision question found in
recent conversation.

**Rule:** All decision points that affect execution flow MUST
use `AskUserQuestion` tool calls, never plain text.

**Why:**
- Plain text does not block execution (agents auto-proceed)
- No structured options (supervisor must type free-form)
- Breaks orchestration contracts in skills

**Correct pattern:**
AskUserQuestion(questions=[{
    question: "Your decision question here?",
    header: "Topic",
    options: [
        {label: "Option A (Recommended)",
         description: "What happens with A"},
        {label: "Option B",
         description: "What happens with B"}
    ],
    multiSelect: false
}])

**References:**
- `.claude/rules/skill-gates.md` — full pattern
- `.claude/rules/essentials.md` § Decision Gates — global scope
- Mark gates with: **REQUIRED: Call `AskUserQuestion`**
```

## When NOT to Reformulate

Skip reformulation for these question types — they are
legitimately plain-text:

- **Clarifying information**: "What's the file name?"
- **Free-text input**: "What should the PR title be?"
- **Confirmations without alternatives**: "Does that look right?"
- **Optional preferences**: user can proceed with defaults

Only reformulate questions where the supervisor must **choose
between discrete alternatives** that change the execution path.

## Examples

### Example 1: Reformulate a recent question

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

### Example 2: Reinforce the convention

**Invocation:** `/Dev10x:ask reinforce`

**Result:** Outputs the reinforcement message from Mode 2
Step 3, citing the specific rules and correct pattern.

### Example 3: Convert a quoted question

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

## Integration

This skill can be referenced by other skills as a
reinforcement mechanism:

- **`Dev10x:diag-friction`** — handles CLI-to-skill
  redirects and permission-friction diagnosis; `Dev10x:ask`
  handles plain-text-to-widget redirects
- **`Dev10x:work-on`** — can invoke `Dev10x:ask reinforce` if
  an agent within the work-on pipeline uses plain text for a
  decision point
- **Skill authors** — reference this skill in SKILL.md when
  documenting decision gates as a fallback enforcement mechanism
