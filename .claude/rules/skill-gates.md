# Skill Decision Gates

Pattern for defining blocking decision points in skills.

## What is a Decision Gate?

A decision gate is a user choice that **affects execution flow** and
**requires blocking** until the user responds. Gates differ from information
questions (which can use plain text):

| Type | Example | Tool Required |
|------|---------|---------|
| Decision Gate | "Resolve thread or leave open?" | AskUserQuestion ✓ |
| Information Question | "What's the PR title?" | Plain text OK |

## Marking Decision Gates

In SKILL.md, mark every decision gate with an explicit enforcement marker:

```markdown
**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
This blocks execution until the user responds. Options:
- Option 1
- Option 2
```

This replaces soft guidance ("Use AskUserQuestion") which allows agents to
substitute plain text instead.

## The Recommended Option Leads, and Reflects State (GH-1404)

Two rules bind every gate, not just the one that prompted them:

1. **Exactly one option carries `(Recommended)`, and it is listed
   first.** An option list with no marker is a gate bypass in the same
   way plain text is: the supervisor is handed a choice with no stated
   default, which is precisely the judgement the gate was supposed to
   pre-digest.
2. **Which option is recommended is computed from state, never fixed
   in prose.** A hard-coded winner is right until the state changes and
   then silently wrong, with nothing to detect it.

GH-1404 is rule 2 failing. The stand-down gate named "Stand down — the
work is complete" as the recommended option unconditionally, while its
only input was an empty task list. Work parked on a tracker issue, a PR
awaiting review, or a promised follow-up is not a task and so cannot
reach that decision — so the gate offered to stop in a session that had
known work outstanding, and the one answer that discards information
led the list.

**When a gate's state is not directly readable, derive it before
offering the choice** rather than guessing in the prescription. The
stand-down gate resolves this by running `Dev10x:ask` Mode 3's
open-loop sweep first and ordering its options from the result:
something pending ⇒ the concrete next action leads; nothing pending ⇒
stand-down leads. A gate that cannot derive its state should say so in
the question rather than assert a default it has not established.

## Checklist for Skill Authors

Before submitting a skill with decision gates, verify all three:

1. ✓ SKILL.md documents gate with **`REQUIRED: Call AskUserQuestion`** marker
2. ✓ Front matter `allowed-tools:` includes `AskUserQuestion` entry
3. ✓ `evals.json` includes assertions for gate enforcement

Missing any step causes per-invocation approval prompts on every skill run.

## Why This Matters

Plain text questions:
- Don't block execution (agents can auto-proceed)
- Lack structured options (no clickable buttons)
- Break the skill's documented orchestration contract

Tool calls ensure:
- User response is mandatory
- Options are presented clearly
- Skill flow is respected

## Evaluation Assertions

When a skill has decision gates, include assertions in `evals/evals.json`:

1. **Gate enforcement** — Verify AskUserQuestion tool calls (not text)
2. **Option correctness** — Check documented options match gate
3. **No auto-resolve** — Confirm user interaction is required
4. **Task tracking** — Validate orchestration state updates

Example signal for detection:
```json
{
  "check": "tool_called",
  "tool": "AskUserQuestion",
  "assertion": "gate1_uses_tool",
  "signal": "AskUserQuestion is called at thread resolution point"
}
```

## When Not to Use AskUserQuestion

Skip tool calls for:
- Clarifying information (e.g., filename, description)
- Confirmations that don't affect workflow
- Optional preferences (user can proceed with defaults)

Reserve gates for choices that **change execution path**.

## Global Scope

This pattern applies **globally** — not only inside loaded skills.
When presenting A/B design choices between skill invocations (e.g.,
architectural trade-offs, strategy options), use `AskUserQuestion`
with structured options. See `essentials.md` § Decision Gates.
