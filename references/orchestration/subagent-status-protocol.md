# Subagent Status Protocol

Structured status reporting for subagents dispatched via `Agent()`,
adapted from the implementer/spec-reviewer pattern in
[obra/superpowers](https://github.com/obra/superpowers).

> **Size-budget override (GH-848, per `.claude/rules/INDEX.md`
> § Budget Overrides).** This file exceeds the 200-line
> `references/**` budget. The status protocol is a single cohesive
> contract — the four statuses, the prompt/delivery templates, the
> escalation ladder, the non-resumable cases, and the addressing
> quirks are read *together* by every orchestration hub (work-on,
> fanout, gh-pr-monitor, skill-audit, adr-evaluate), and splitting
> them would scatter one contract across files that must stay in
> sync. **Conditional split seam:** if this file grows past 300
> lines, split the core protocol (statuses, prompt template,
> delivery channel) from the operational guidance (escalation
> ladder, non-resumable cases, addressing quirks, adoption
> checklist).

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

## Delivery channel — background vs synchronous (GH-776)

The status line rides on the agent **result**. How that result
reaches the controller depends on how the agent was dispatched:

| Dispatch | Delivery of the result |
|----------|------------------------|
| Synchronous (`run_in_background=false`) | Final text IS the result — the trailing status line is parsed directly. |
| Named background (`run_in_background=true`, `name=...`) | Plain text is **NOT delivered**. The controller only receives an `idle_notification` with no content. The status line never arrives on its own. |

For named background agents the ONLY working delivery channels are:

1. `SendMessage(to="main", summary="<5 words>", message=<full
   report ending with the status line>)`.
2. Write the report to the agent's scratchpad path, then a one-line
   `SendMessage` confirming the path (fallback for oversized reports).

Therefore every **background** dispatch prompt MUST append the
delivery instruction in addition to the status template. The single
importable source is `BACKGROUND_DELIVERY_TEMPLATE` in
`dev10x.skills.orchestration.subagent_protocol` (sibling of
`STATUS_PROMPT_TEMPLATE`).

### Addressing the orchestrator (GH-848 F1)

`SendMessage(to="main", …)` is the documented default, but some
harness configurations reject the literal `"main"` recipient with
**"Send to a named agent instead"** — in those configs `"main"` is
not a registered addressee. When a dispatched agent sees that
rejection, it MUST retry addressing the orchestrator by the **actual
name/ID it was told to report to** at dispatch, not the literal
string `"main"`. To make this unambiguous, an orchestrator that
runs under a non-default name SHOULD state its own address in the
dispatch prompt (e.g. "deliver via `SendMessage(to=\"team-lead\", …)`")
rather than relying on the `"main"` alias. The `BACKGROUND_DELIVERY_TEMPLATE`
keeps `"main"` as the default; skills whose orchestrator is named
override the recipient when constructing the prompt.

### `TaskOutput` does not reach `Agent`-tool teammates (GH-848 F3)

Do NOT try to retrieve a background teammate's result with
`TaskOutput(task_id=…)`. Agents spawned via the `Agent` tool are not
task-runner processes — `TaskOutput` returns "No task found" for
them. Their ONLY result channel is the `SendMessage` delivery above.
`TaskOutput` is valid only for work started through the task runner,
never for `Agent`-dispatched teammates.

### Escalation ladder for a silent agent

An `idle_notification` with no content means the agent finished
**without delivering** — not that it is still working. Do not treat
it as `DONE`. Escalate:

1. **One nudge** — `SendMessage` the agent: "Your plain text is not
   visible; call SendMessage(to=\"main\", …) with your report."
2. **File fallback** — instruct it to Write the report to its
   scratchpad path and send a one-line confirmation.
3. **`TaskStop`** — if still silent after the file fallback, stop the
   agent and fall back to main-session execution (treat as `BLOCKED`).

Evidence (session 2026-07-07, PR #772): five research agents
dispatched with the status template alone delivered zero reports
spontaneously; recovery required the ladder above.

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

**Non-resumable cases — skip the resume attempt (GH-848 F2, GH-873 F2):**
Resume-first is correct only for agents that are still resumable. Two
failure modes are NOT resumable and a `SendMessage` resume against them
wastes a round-trip before failing:

- **Account/session-limit kill (GH-848 F2)** — when the agent was
  terminated because the account hit its usage/session limit (not a
  per-turn budget), the agent context is gone; a resume returns
  nothing. Recover by **respawning a fresh agent** with the original
  prompt plus the last known PR URL/branch (see the re-dispatch
  fields below) — do not attempt a resume first.
- **User-killed via `TaskStop` (GH-873 F2)** — an agent the supervisor
  (or the orchestrator) stopped with `TaskStop` will not resume, even
  in the same session. Do NOT send it a continuation prompt. Go
  straight to salvaging its work: finish the remaining lifecycle
  inline in the orchestrator, or cherry-pick its commits onto a fresh
  branch (the cross-repo salvage path). Treat a user-killed agent the
  same as `BLOCKED` for routing purposes.

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
