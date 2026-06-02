# Decision Gate: Lightweight Audit Disposition (GH-436)

Fired by Phase 0 (lightweight strategy) after the agent presents
inline findings from the visible conversation context. Routes to
file, escalate to forensic, or discard — without spending wave
subagent calls.

```
AskUserQuestion(questions=[{
    question: "Inline findings are ready from the visible context "
              "(see summary above). How should we proceed?",
    header: "Disposition",
    options: [
        {label: "Select & file now (Recommended)",
         description: "Present structured selection, then delegate to "
                      "Dev10x:audit-file via Phase 7 — no transcript "
                      "extraction or wave subagents dispatched"},
        {label: "Run forensic audit",
         description: "Escalate to full transcript extraction and "
                      "Wave 1 + Wave 2 subagents before filing. "
                      "Run from a separate terminal."},
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
| Select & file now | Create minimal task list (`Phase 0: Inline findings` + `Phase 7: Upstream reporting`). Skip Steps 0–8 and Phases 1–6. Jump directly to Phase 7 with inline findings as the scrubbed findings file. Phase 7 sub-steps A–D still run. |
| Run forensic audit | Fall through to Step 0 (Initialize forensic task tracking) and continue the standard wave orchestration. |
| Discard | Exit the skill; do not create wave tasks, do not delegate to `Dev10x:audit-file`. |

The "Select & file now" branch MUST still pass through the
Phase 7 sub-steps (collect → confirm → scrub → delegate) —
the gate replaces the analysis waves, not the upstream
reporting pipeline.
