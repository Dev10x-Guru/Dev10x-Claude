# Auto-Advance Universal Rule

This rule applies to ALL skills, regardless of tier. It is the
single most important orchestration pattern.

**Always auto-advance — no checkpoints under adaptive friction.**
Complete a step or task, immediately start the next. Never pause
to ask "should I continue?", "ready for the next step?", or wait
for the user to say "go" / "next" / "continue". The invocation of
the skill is the authorization to proceed through all its steps.
See `references/friction-levels.md` § "No checkpoints" rule for
the canonical definition of what counts as a checkpoint vs. a
legitimate gate or dependency wait.

```
TaskUpdate(taskId=current, status="completed")
TaskUpdate(taskId=next, status="in_progress")
# Begin next task work immediately — no pause
```

**Routine confirmations are not decisions** — skip progress
acknowledgments and "looks good?" checks. Keep going.

## Batched Decision Queue

When a task hits a genuine A/B decision that cannot be inferred
from context, do NOT interrupt the user immediately. Instead:

1. **Queue the decision** — record it in task metadata:
   ```
   TaskUpdate(taskId, status="pending",
       metadata={"decision_needed": "Which strategy: fixup vs restructure?",
                 "options": ["Fixup", "Full restructure", "Mass rewrite"]})
   ```
2. **Move to the next unblocked task** — continue advancing on
   any task that doesn't require this decision.
3. **Only interrupt when fully blocked** — when NO tasks can
   advance further without user input, collect ALL queued
   decisions into a single `AskUserQuestion` batch:
   ```
   AskUserQuestion(questions=[
       {question: "git-groom: Which restructuring strategy?",
        header: "Strategy", options: [...], multiSelect: false},
       {question: "scope: Approve context findings?",
        header: "Findings", options: [...], multiSelect: false},
       {question: "PR: Which comments to address?",
        header: "Comments", options: [...], multiSelect: true},
   ])
   ```
4. **Unblock and resume** — after the user answers, update all
   relevant tasks and resume auto-advancing.

**Why batch?** The supervisor should be able to step away, come
back to answer all pending decisions at once, then step away
again confident that maximum progress will happen before the
next interruption. One batch of 3 questions is better than 3
separate interruptions spaced minutes apart.

**AskUserQuestion supports 1-4 questions per call.** If more
than 4 decisions are queued, prioritize by dependency order —
ask decisions that unblock the most downstream work first.

**Always queue, never ask inline.** Even single-task skills
must queue their decisions rather than asking immediately. The
skill does not know whether other skills or agents are running
in parallel with their own pending decisions. The orchestrator
(session or work-on) collects all queued decisions and presents
them as a batch. This ensures the supervisor is interrupted
once with N questions, not N times with 1 question each.

## Anti-Pattern: Orchestrator Self-Assessment

**Pattern**: Orchestrator inspects state (commit history, PR status,
file contents) to decide whether a delegated step is needed, then
optionally skips the delegation.

**Why this fails**: Skills contain decision gates (AskUserQuestion,
conditional logic) that represent team policy and operational
constraints. Bypassing them via orchestrator assessment loses:
- Audit trail of decision rationale
- User interaction (user never sees the gate)
- Regression prevention (no evals track this decision)

**Required pattern**: Always delegate; let the skill run its own
analysis and return a decision. The orchestrator must NOT
pre-assess or post-assess to override.
