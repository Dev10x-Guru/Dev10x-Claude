# Subagent Status Operations

Operational guidance for running the
[subagent status protocol](subagent-status-protocol.md): how to reach
the orchestrator, what to do when an agent goes silent or dies, and
how a skill adopts the protocol. The statuses, prompt template,
delivery channel and parse pattern live in the protocol file; read it
first (GH-1892).

## Delivery quirks

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

**A subagent orchestrator has no named roster at all (GH-965).**
`Agent(..., name=...)` fails from inside an agent — *"teammates
cannot spawn teammates"* — so a nested orchestrator (e.g.
`dev10x:foreman`) addresses its workers only by the raw `agentId`
from the spawn result. That is the *less* durable handle: names
survive an agent's completion, an `agentId` does not survive a
session death (below). Plan to respawn, not to message.

### `TaskOutput` does not reach `Agent`-tool teammates (GH-848 F3)

Do NOT try to retrieve a background teammate's result with
`TaskOutput(task_id=…)`. Agents spawned via the `Agent` tool are not
task-runner processes — `TaskOutput` returns "No task found" for
them. Their ONLY result channel is the `SendMessage` delivery in
[§ Delivery channel](subagent-status-protocol.md#delivery-channel--background-vs-synchronous-gh-776).
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

## Recovering an unfinished agent

An agent that ends without `DONE` — interrupted, out of turns, or
with no status line at all — is routed per the protocol's
[§ Controller parse pattern](subagent-status-protocol.md#controller-parse-pattern).
This section decides how to bring it back.

**Resume-first recovery (GH-462 F1):** Before re-dispatching a
fresh agent, attempt a **SendMessage resume** of the same agent —
send a short continuation prompt (e.g., "Please continue and
finish through to PR merge"). This preserves the agent's full
in-context state (PR branch, CI results, diff history) and
typically completes the lifecycle at lower cost. Re-dispatch a
fresh agent only when the agent is no longer resumable (turn
expired, session ended, or the original agent returned BLOCKED).

**Resume works within the dispatching session only (GH-965).** An
agent that merely ended its turn is resumable; a **session death**
discards every transcript, so `SendMessage` to a prior session's
`agentId` returns *"No transcript found for agent ID"* even though
the ID is well-formed and its commits are intact on origin. Both
cases are called "resume" and behave oppositely — a plan built on
messaging a previous session's agents is dead on arrival. Full
durability contract:
[`../../skills/foreman/references/durability-envelope.md`](../../skills/foreman/references/durability-envelope.md).

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
