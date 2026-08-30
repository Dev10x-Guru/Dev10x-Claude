# Reinforcement Message Template (Mode 2, Step 3)

Output this structure verbatim, substituting the offending
question. See `SKILL.md` § Mode 2 for when it fires.

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

Mode 2 is a nudge, not a decision point: do NOT call
`AskUserQuestion` while emitting it — there is no supervisor
choice to block on.
