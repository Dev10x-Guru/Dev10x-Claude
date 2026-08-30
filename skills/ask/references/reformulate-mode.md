# Mode 1: Reformulate — Scope and Procedure

Detail for `SKILL.md` § Mode 1. Step 3 (the `AskUserQuestion`
gate) stays in SKILL.md because it gates execution; everything
here is the procedure around it.

## Step 1: Scan recent conversation

Look back through the most recent 10-15 conversation turns for
plain-text questions directed at the supervisor. A question
qualifies for reformulation when ALL of these are true:

1. It asks the supervisor to **choose** between alternatives,
   **decide** on an approach, or **approve/reject** something
2. It was asked as plain text (not via `AskUserQuestion`)
3. It has not already been answered by the supervisor

Skip questions that are purely informational (e.g., "What's the
file path?", "Can you clarify the requirement?").

## Step 2: Extract and structure each question

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

## Step 4: Report results

After the supervisor responds, output a brief summary:

- How many questions were reformulated
- The supervisor's choices
- Any questions that were skipped (with reason)

## When NOT to reformulate

Skip reformulation for these question types — they are
legitimately plain-text:

- **Clarifying information**: "What's the file name?"
- **Free-text input**: "What should the PR title be?"
- **Confirmations without alternatives**: "Does that look right?"
- **Optional preferences**: user can proceed with defaults

Only reformulate questions where the supervisor must **choose
between discrete alternatives** that change the execution path.

Such a question may still be an open loop worth tracking. Mode 3
records it as a task without forcing it into a widget — being
unanswered and being decision-shaped are independent properties,
and only the second one earns a gate.
