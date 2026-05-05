# Subagent Status Protocol

Structured status reporting for subagents dispatched via `Agent()`,
adapted from the implementer/spec-reviewer pattern in
[obra/superpowers](https://github.com/obra/superpowers).

## Why a status protocol

Dev10x orchestration hubs (work-on, fanout, skill-audit,
gh-pr-monitor, adr-evaluate) interpret subagent results
heuristically today. A subagent that hits a permission wall, runs
out of context, or finishes successfully all return free-form
prose — the controller has to guess.

A structured terminal status line lets the controller branch
deterministically: re-dispatch with more context, surface a
decision gate to the user, or mark the task done. It also gives
the user a stable signal across all skills.

## The four statuses

Every subagent prompt MUST instruct the agent to end its output
with exactly one of:

| Status | Meaning | Controller action |
|--------|---------|-------------------|
| `DONE` | Task complete, all acceptance criteria met | Mark task `completed`, continue pipeline |
| `DONE_WITH_CONCERNS: <text>` | Task complete but flagged issues | Mark `completed`, surface concerns to user via batched decision queue |
| `NEEDS_CONTEXT: <what>` | Cannot proceed without more input | Re-dispatch with the requested context, OR escalate via `AskUserQuestion` |
| `BLOCKED: <reason>` | Permission wall, missing tool, or unrecoverable error | Fall back to main-session execution (GH-901) and surface the reason |

The status MUST be the **last non-empty line** of the agent
result. Controllers parse the trailing line of the result string
with a strict prefix match.

## Prompt template

Every Agent dispatch from an orchestration skill should include
this block near the end of the prompt:

```
Report your final status as the LAST line of your output, with
exactly one of these prefixes:

- DONE                           — task complete
- DONE_WITH_CONCERNS: <text>     — complete but flagged
- NEEDS_CONTEXT: <what>          — re-dispatch needed
- BLOCKED: <reason>              — cannot proceed (permission,
                                    missing tool, unrecoverable)

Do not write anything after the status line.
```

## Controller parse pattern

Pseudo-code for the controller side:

```
result = Agent(...)
status_line = result.strip().splitlines()[-1]

if status_line == "DONE":
    TaskUpdate(taskId=..., status="completed")
elif status_line.startswith("DONE_WITH_CONCERNS:"):
    TaskUpdate(taskId=..., status="completed")
    queue_decision(status_line[len("DONE_WITH_CONCERNS:"):].strip())
elif status_line.startswith("NEEDS_CONTEXT:"):
    redispatch_with_more_context(status_line)
elif status_line.startswith("BLOCKED:"):
    fallback_to_main_session(reason=status_line)
else:
    # Treat as BLOCKED — protocol violation
    fallback_to_main_session(reason="missing status line")
```

## When to use which status

**DONE** is the default. Use it whenever acceptance criteria are
met, even if the agent had to retry or work around minor issues.

**DONE_WITH_CONCERNS** is for "I finished the task, but the user
should know X." Examples:
- Code compiles but tests were skipped
- PR comment addressed but a related concern was discovered
- Investigation found root cause AND a tangential bug

**NEEDS_CONTEXT** is for "I cannot complete this without input
the controller can provide." Examples:
- File mentioned in prompt does not exist — needs a corrected path
- Prompt referenced a ticket but the ticket body was not included
- Required environment variable not declared

The controller should re-dispatch with the requested context.
Avoid using NEEDS_CONTEXT when the right answer is to ask the
user — use BLOCKED with a clear reason instead.

**BLOCKED** is for permission walls and unrecoverable errors.
This is the signal that triggers the GH-901 main-session
fallback. Examples:
- Bash command denied even with `mode: "dontAsk"`
- Required MCP tool unavailable
- Worktree creation failed
- External service (gh, Linear, Sentry) returned auth error

## Relationship to existing fallback patterns

`gh-pr-monitor`'s GH-901 main-session fallback currently triggers
on heuristic agent-failure detection (timeouts, unexpected exit
codes). Adopting BLOCKED as an explicit status removes the
guesswork: the agent self-reports the failure mode, and the
controller's fallback path runs without ambiguity.

`skill-audit`'s "return findings as strings" inversion (Wave 2,
GH-565) becomes simpler too: each Wave 2 subagent returns
findings followed by `DONE`, and the synthesis phase parses both
the findings and the status uniformly across phases.

## Adoption checklist

When updating an orchestration skill to use this protocol:

1. ✓ Every `Agent()` dispatch prompt includes the status template
2. ✓ Controller parses the last line and branches on the status
3. ✓ `BLOCKED` triggers the same fallback as today's heuristic
   detection (no behavior change for the user, just a clearer
   signal)
4. ✓ `DONE_WITH_CONCERNS` items are queued for batched decision
   presentation per `references/orchestration/decision-gates.md`
5. ✓ Reviewer-skill spec (item 14a or new item) flags missing
   status protocol in dispatched-prompt sections

## Skills to migrate

Priority order (highest leverage first):

1. `skills/fanout/` — multi-item fanout benefits most from
   deterministic status parsing
2. `skills/gh-pr-monitor/` — replaces heuristic fallback
   (GH-901)
3. `skills/skill-audit/` — Wave 2 phases unify their result
   shape
4. `skills/work-on/` — Phase 2 Gather and Phase 3 execution
   subagents
5. `skills/adr-evaluate/` — architect dispatches

Each migration is an independent PR. Update the SKILL.md
prompt-construction sections and any `references/phases.md` /
`references/example-plays.md` files; do not change `allowed-tools`
or agent specs.
