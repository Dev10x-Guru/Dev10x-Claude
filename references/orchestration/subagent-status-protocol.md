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
> sync. **Split due, tracked in GH-1892.** The file has passed its
> 300-line trigger. Split the core protocol (statuses, prompt
> template, delivery channel) from the operational guidance
> (escalation ladder, non-resumable cases, addressing quirks,
> adoption checklist).

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
| `BLOCKED: <reason>` | Permission wall, missing tool, or unrecoverable error | Fall back to main-session execution (GH-901) and surface the reason — **except a hook denial**: any `BLOCKED` line that mentions a hook (canonically `BLOCKED: hook denied <command>`) is surfaced and the denied command is never re-run (see § Hook denials) |

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
- BLOCKED: hook denied <command> — a hook refused a command; stop,
                                    do not try another shape

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

## Controller parse pattern

Pseudo-code for the controller side:

```
result = Agent(...)
status_line = result.strip().splitlines()[-1]
# both from dev10x.skills.orchestration.subagent_protocol
parsed = parse_subagent_status(result=result)

if is_hook_denial(parsed=parsed):
    # any BLOCKED or malformed line that mentions a hook (GH-1874)
    surface_to_supervisor(reason=status_line)  # never re-run it
elif status_line == "DONE":
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
Orchestrators MUST treat it as `NEEDS_CONTEXT` — unless that last
line mentions a hook, which the controller checks first and surfaces
as a hook denial (see § Hook denials, GH-1874).

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

### Hook denials are surfaced, not re-run (GH-1874)

A subagent that reports `BLOCKED: hook denied <command>` hit a
PreToolUse guardrail, not a permission gap. The GH-901 fallback would
have the controller run the same command in the main session, where
the same hook denies it again — or, worse, where a looser allow rule
lets it through and the guardrail is bypassed by a change of seat.

1. Surface the denied command to the supervisor through the batched
   decision queue (`AskUserQuestion` when every task is blocked), the
   same routing `dev10x:fanout` already uses.
2. Re-dispatch only with a brief that names the sanctioned tool for
   that command — the skill or MCP wrapper the hook's message points
   to. Never re-dispatch the same brief.
3. Never run the denied command from the main session, and never ask
   the subagent to find another shape for it.

`BLOCKED: hook denied <command>` is the canonical wording.
`is_hook_denial()` treats a `BLOCKED` or unreadable (malformed) status
line as a denial when it contains the word `hook` or `hooks`, in any
case. It errs toward surfacing: a false match only surfaces a report
that could have been retried, while a miss re-runs a command a hook
refused. It reads only that last line, and it does not catch a refusal
that never uses the word, such as `PreToolUse denied …` or
`pre_hook …` — which is why subagent briefs ask for the canonical
wording.

Every other `BLOCKED` reason keeps the main-session fallback above.
