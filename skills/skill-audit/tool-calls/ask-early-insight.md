# Decision Gate: Early-Insight Disposition

Fired by Phase 0 when the agent has detected a narrow,
transcript-evident question and prepared findings inline.
The gate routes the agent to the correct disposition without
spending wave subagent calls.

```
AskUserQuestion(questions=[{
    question: "Findings are ready from the visible transcript "
              "(see inline summary above). How should we proceed?",
    header: "Disposition",
    options: [
        {label: "Select & file now (Recommended for clear findings)",
         description: "Skip to Phase 7 and delegate to "
                      "Dev10x:audit-report with the pre-formed "
                      "findings — no wave subagents dispatched"},
        {label: "Step back and run full audit",
         description: "Proceed to Step 0 and run the standard "
                      "Wave 1 + Wave 2 subagents before filing"},
        {label: "Discard — no action needed",
         description: "Exit without filing; findings remain "
                      "only in the conversation"}
    ],
    multiSelect: false
}])
```

## Branching after the gate

| User choice | Next action |
|-------------|-------------|
| Select & file now | Create minimal task list (early-insight + select-and-file), skip Steps 0–8 and Phases 1–6, jump directly to Phase 7 with the inline findings as the scrubbed findings file |
| Step back and run full audit | Fall through to Step 0 (Initialize task tracking) and continue the standard wave orchestration |
| Discard | Exit the skill; do not create wave tasks, do not delegate to `Dev10x:audit-report` |

The "Select & file now" branch MUST still pass through the
existing Phase 7 sub-steps (collect → confirm → scrub →
delegate) — the gate replaces the analysis waves, not the
upstream reporting pipeline.
