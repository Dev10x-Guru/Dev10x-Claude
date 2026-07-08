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

## Delivering the status line: background vs foreground (GH-776)

**How the status line reaches the controller depends on how the
agent was dispatched — the "last line of output" contract above
holds for foreground agents only.**

- **Foreground `Agent()`** (awaited, no `run_in_background`): the
  agent's final message IS the tool-result string, so the status
  line rides on its last line and the controller parses it
  directly (see Controller parse pattern below).

- **Background / named `Agent(..., run_in_background=true,
  name=...)`**: the agent's final plain-text message is **NOT**
  delivered to the orchestrator — the orchestrator only receives a
  content-less `idle_notification`. Plain stdout is invisible here;
  an `idle_notification` with no content means the agent finished
  **without** delivering its report. The only channels that work:

  1. `SendMessage(to="main", summary="<5 words>", message=<full
     report whose LAST line is the status line>)`.
  2. Write the report to a scratchpad file and confirm the path
     via a one-line `SendMessage`.

  So a background-agent prompt MUST end with an explicit delivery
  instruction, not merely "end with a status line". Append:

  ```
  Your plain-text output is NOT visible to the orchestrator.
  Deliver your report by calling SendMessage(to="main",
  summary="<5 words>", message=<full report whose LAST line is
  your status line: DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT /
  BLOCKED>). If the report exceeds one message, split it into
  labeled parts. Fallback: Write the report to <scratchpad path>
  and send a one-line confirmation of the path.
  ```

**Escalation ladder for a silent background agent (GH-776):**

1. One nudge — `SendMessage(to=<agent>, "Your plain text is not
   visible; call SendMessage(to=\"main\", ...) with your report.")`.
2. File fallback — tell the agent to Write the report to a
   scratchpad path and confirm the path in a one-line SendMessage.
3. `TaskStop` — if it still emits only idle notifications, stop it
   and treat the missing report as `NEEDS_CONTEXT`.

The same evidence (session 2026-07-07, PR #772) showed
`shutdown_request` ignored by 4 of 7 agents — do not rely on a
cooperative shutdown; `TaskStop` is the backstop.

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
    # Missing or non-terminal trailing line (GH-368 F2, GH-385 F1)
    # Treat as NEEDS_CONTEXT — agent was interrupted before completion.
    # Do NOT treat as DONE — the task state is unknown.
    redispatch_with_more_context(
        "NEEDS_CONTEXT: agent terminated without a status line — "
        "re-dispatch to complete remaining lifecycle"
    )
```

For a background / named agent, `result` above is the text the
agent delivered via `SendMessage(to="main", ...)` (or the
confirmed scratchpad file) — never raw stdout, which the
orchestrator does not receive (see § Delivering the status line).

**Missing status line handling (GH-368 F2, GH-385 F1):** When
a swarm agent hits a context limit, permission wall, or turn
budget before finishing the PR lifecycle, it may terminate
with free-form prose as its last line. This is NOT `DONE`.
Orchestrators MUST treat it as `NEEDS_CONTEXT`.

**Resume-first recovery (GH-462 F1):** Before re-dispatching a
fresh agent, attempt a **SendMessage resume** of the same agent —
send a short continuation prompt (e.g., "Please continue and
finish through to PR merge"). This preserves the agent's full
in-context state (PR branch, CI results, diff history) and
typically completes the lifecycle at lower cost. Re-dispatch a
fresh agent only when the agent is no longer resumable (turn
expired, session ended, or the original agent returned BLOCKED).

When a fresh re-dispatch is needed, the prompt should include:
- The last known PR URL (if visible in the result)
- The last known branch name
- A directive to continue from the current PR state rather
  than restarting from scratch

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
- Turn ended before the PR was merged (branch or PR exists but
  is still open) — include the PR URL so the orchestrator can
  re-dispatch to the monitor → merge lifecycle

The controller should re-dispatch with the requested context.
Avoid using NEEDS_CONTEXT when the right answer is to ask the
user — use BLOCKED with a clear reason instead.

**NEEDS_CONTEXT for interrupted merge lifecycle (GH-368, GH-385):**
When a swarm agent has created a PR but cannot finish the
monitor → merge lifecycle (context limit, turn budget, or
interruption), it MUST use `NEEDS_CONTEXT: PR open at <url>,
merge not complete` rather than `DONE`. The `DONE` status
requires the PR to be MERGED — an open PR is not done.

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
