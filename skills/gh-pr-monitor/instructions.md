# PR Review Monitor — Instructions

## Overview

This skill drives a supervised PR-shepherding loop in the
supervisor's own session, dispatching narrow read-only haiku
micro-agents for the bounded mechanical work (CI polling, thread
scanning). The supervisor interprets every signal and owns every
decision. The historical "launch a background agent that
autonomously monitors everything" design was retired in GH-68
after a recurring incident where the background haiku decided
on its own to revert reviewer-directed code.

**When to use this skill:**
- After creating a draft PR with `/dev10x:gh-pr-create`
- When you want to automate the PR review cycle without blocking your session

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**Auto-advance:** Complete each phase, immediately start the next — no checkpoints the resolver did not ask for.
Never pause to ask "should I continue?" between phases.

**REQUIRED: Create tasks at session start.** The supervisor
creates these `TaskCreate` calls before dispatching any micro-agent:

1. `TaskCreate(subject="Detect PR context and launch agent", activeForm="Detecting PR context")`
2. `TaskCreate(subject="Check JTBD Job Story (Phase 0)", activeForm="Checking Job Story")`
2b. `TaskCreate(subject="Confirm PR is ready for review (Phase 0.5)", activeForm="Confirming review readiness")`
3. `TaskCreate(subject="Monitor CI checks (Phase 1)", activeForm="Monitoring CI")`
4. `TaskCreate(subject="Address review comments (Phase 2)", activeForm="Addressing comments")`
5. `TaskCreate(subject="Assess QA scope (Phase 2.5)", activeForm="Assessing QA scope")`
6. `TaskCreate(subject="Notify re-review (Phase 2.7)", activeForm="Notifying re-review")`
7. `TaskCreate(subject="Send review notification (Phase 3)", activeForm="Sending notification")`
8. `TaskCreate(subject="Verify acceptance criteria (Phase 4)", activeForm="Verifying acceptance criteria")`

Set dependencies: each phase blocked by its predecessor. Phases
2.5 and 2.7 are conditional — skip via TaskUpdate status="deleted"
when their trigger conditions are not met.

**Background agents:** This skill already uses a background Task
agent. Task tracking wraps the agent phases so the supervisor
sees progress without reading the agent output file.

## Execution Model

```
User invokes /dev10x:gh-pr-monitor
    │
    └── Supervisor session IS the orchestrator (GH-68)
            │
            ├── Phase 0: JTBD Job Story check (supervisor)
            │       └── Skill(dev10x:ticket-jtbd) if missing
            │
            ├── Phase 0.5: Review-readiness precondition (supervisor)
            │       └── pr_get → isDraft; pr_ready if still draft
            │
            ├── Phase 1: CI monitoring
            │       ├── dispatch micro-agent: haiku-ci-poll
            │       │     (loops ci-check-status until verdict ≠ pending)
            │       └── supervisor interprets verdict → next action
            │
            ├── Phase 2: Comment monitoring
            │       ├── dispatch micro-agent: haiku-thread-scan
            │       │     (read-only enumerate unresolved threads + findings)
            │       └── supervisor invokes Skill(dev10x:gh-pr-respond)
            │
            ├── Phase 2.5: QA scope (supervisor + Skill(qa-scope))
            ├── Phase 2.7: Re-review notification (supervisor)
            ├── Phase 3: Notification (supervisor + AskUserQuestion)
            └── Phase 4: Acceptance criteria (Skill(verify-acc-dod))
```

**Why this shape (GH-68 incident #2):** the prior model dispatched
a single fat haiku agent in background with `mode: dontAsk` and
`max_turns: 200`. That agent encountered a CI failure, rationalised
that the right fix was to revert reviewer-directed code, and
auto-grooved the regression into the squashed history. Removing
decision-making capacity from the place it kept being abused —
the haiku — and keeping orchestration in the supervisor's session
removes the entire failure surface.

**Trade-off:** the skill no longer runs unattended after launch.
The supervisor must remain available to interpret micro-agent
signals between turns. In exchange, micro-agents cannot mutate
source files, cannot decide between code changes, and cannot
delegate further. The user explicitly chose this trade-off
(GH-68 follow-up).

## Launch Instructions

When the user invokes `/dev10x:gh-pr-monitor`:

### Step 1: Detect PR context

**Primary (MCP tool):** Call `mcp__plugin_dev10x_cli__pr_detect`
with the PR argument (URL, bare number, or empty). Parse
`PR_NUMBER`, `REPO`, `PR_URL`, `BRANCH` from the response.

**MCP server unavailable.** If the tool is listed as "no longer
available" in system-reminders, STOP and ask the user to reconnect
via `/mcp` or a session restart. Do NOT fall back to the wrapper
script or env-level bypasses — see
`references/mcp-unavailable-escape-hatch.md`.

**Fallback (script):** Only when the MCP server is healthy but the
tool call errored for another reason:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/gh-context/scripts/gh-pr-detect.sh "$ARG"
# Parse PR_NUMBER, REPO, PR_URL, BRANCH from KEY=VALUE stdout
```

Pass `$ARG` as the skill argument (PR URL, bare number, or empty).
Both methods fetch `BRANCH` via `gh pr view --json headRefName`
— never from local git — which is critical in multi-worktree setups.

If the script exits non-zero, tell the user and stop.

### Step 2: Check for resume state

Read the state file at `/tmp/Dev10x/pr-monitor/state-{pr_number}.json`
(if it exists). If `phases_completed` contains both `phase0` and
`phase3`, the supervisor can skip directly to a lightweight CI-poll
loop instead of re-running every phase — dispatch only
`haiku-ci-poll` and emit a fresh ready/notify cycle if anything
changed. The earlier "background poll vs full agent" choice no
longer applies — there is only one execution model now (foreground
supervisor + micro-agents), this is just a phase-skip optimisation.

### Step 3: Enter orchestrator loop (GH-68)

This skill no longer launches a background agent. The supervisor's
session is the orchestrator and dispatches narrow micro-agents
for the bounded read-only work. See "Micro-Agents" below for the
two specs (`haiku-ci-poll`, `haiku-thread-scan`).

The supervisor walks Phases 0 → 4, interpreting each micro-agent's
returned JSON between dispatches.

**Surface launch parameters (GH-127 #6).** Before each
`Agent(...)` dispatch, print a one-line startup banner so the
supervisor can confirm the run-time parameters were honored:

```
[gh-pr-monitor] dispatch=haiku-ci-poll model=haiku max_turns=50 background=true pr=#{N}
```

**Exit-reason taxonomy (GH-127 #6).** Each micro-agent's final
JSON line is the canonical exit reason. The supervisor MUST
classify the result before deciding next action:

| `verdict` | Meaning | Supervisor action |
|---|---|---|
| `green` / `failing` / `conflicting` | Completed normally | Branch on verdict (Phase 2+) |
| `infra_unavailable` | `wait=true` budget exhausted while checks never registered — hosted-runner/infra outage, not a transient pending (GH-808 F2) | Do NOT read as failing. Re-invoke `ci_check_status(wait=true)` to detect recovery; if it recurs, **REQUIRED: Call `AskUserQuestion`** (keep waiting / escalate) |
| `timeout` | Hit `max_turns` budget without resolution | Re-dispatch with the same prompt (CI just slow) |
| missing JSON line | Permission denied or hard crash | Inspect transcript; do NOT silently re-dispatch — surface the failure to the user |
| explicit `"error": …` | The agent reported an error and exited | Propagate the error message to the user |

The "permission denied vs budget exhausted" distinction matters
for re-dispatch decisions: budget exhaustion is safe to retry,
permission denial is not.

### Micro-Agents (GH-68)

The two micro-agent specs — `haiku-ci-poll` (Micro-agent A) and
`haiku-thread-scan` (Micro-agent B), with the friction-avoidance
preamble, tool allowlists and prompts — live in
[`references/phase-micro-agents.md`](references/phase-micro-agents.md).
Read it before the first `Agent(...)` dispatch.

### Step 4: Announce orchestration to user

There is no background agent to point at. The supervisor IS the
orchestrator. Announce the plan briefly so the user understands
the new model:

> Monitoring PR #{pr_number} ({pr_url}). I'll run Phase 0–4 in
> this session: ci-poll runs in the background while I work on
> other things; thread-scan runs inline. I'll surface
> `AskUserQuestion` gates at Phase 2.5 (QA), 2.7 (re-review),
> and 3 (notification).

Task tracking from the parent orchestration contract (the eight
phase tasks at the top of this file) provides per-phase
visibility — no extra "monitor running" task is needed because
the supervisor's foreground turns ARE the monitoring.

---

## Orchestrator Phase Reference

These are the procedures the supervisor walks while monitoring
PR `#{pr_number}`. They are NOT a prompt to embed in a background
agent — the supervisor session executes them directly, dispatching
the two micro-agents (`haiku-ci-poll`, `haiku-thread-scan`) for
the bounded read-only work and interpreting their JSON returns.

### Step 0: Load supervisor directives and memory (GH-68, Fix B + D)

Before entering Phase 0, the supervisor loads two sources of
constraints into its own context and treats them with the same
authority as user instructions:

**Directives from the user's invocation arguments.** Scan the
args passed to `/dev10x:gh-pr-monitor` (case-insensitive) for:

- `do NOT ...` / `do not ...` (capture trailing clause up to
  newline or `.`)
- `INTENTIONALLY ...`
- `leave UNSQUASHED` / `leave unsquashed`
- `do NOT auto-groom` / `no auto-groom`
- `keep ... open` / `do not resolve`
- Any line beginning with `MUST NOT` or `NEVER`

Restate each matched directive verbatim at the start of the
supervisor's monitoring plan ("Per the dispatch prompt: …"). Before
invoking `Skill(dev10x:git-groom)`, `Skill(dev10x:gh-pr-respond)`,
or making any code change, re-read these directives and confirm
the planned action does not match a prohibition. If it does,
stop, summarise the conflict, and ask the user — never improvise
around the prohibition.

**Persistent guardrails from supervisor memory.** Read files
matching `feedback_monitor*` or `feedback_*monitor*` from:

```bash
ls "$CLAUDE_PROJECT_DIR/.claude/memory/" 2>/dev/null \
  | grep -E 'feedback_monitor|feedback_.*monitor' \
  || true
ls "$HOME/.claude/projects/$(basename "$PWD")/memory/" 2>/dev/null \
  | grep -E 'feedback_monitor|feedback_.*monitor' \
  || true
```

For each match, Read the file body and incorporate it into the
monitoring plan as durable guardrails. The GH-68 incident #2
finding: the user had `feedback_monitor_agent_respects_design_
decisions.md` written 13 days before the second incident, and the
prior implementation never read it.

### Mission

Shepherd this PR from draft → CI passing → comments addressed →
review requested → acceptance verified. Source-file mutations
require explicit supervisor reasoning (this session) — not a
sub-agent. Sub-agents only return signals.

---

## Early-Exit Check

Before running any phases, check if work has already been done by
reading the state file and comparing against current PR state.

1. Read `/tmp/Dev10x/pr-monitor/state-{pr_number}.json` (if exists)
2. Fetch current PR state:
   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-monitor/scripts/ci-check-status.py \
     --pr {pr_number} --repo {repo}
   gh pr view {pr_number} --repo {repo} --json state,reviews,comments
   ```
3. Compare against saved state
4. If ALL match and no new data → exit with:
   "No changes since {last_checked}. Nothing to do."
5. If changed → run only the relevant phases
6. Skip phases listed in `phases_completed` from the state file

---

## Phase Index

Each phase body lives in its own file under `references/`. Read the
file for a phase when the supervisor reaches it. Phase 3 stays in one
file so its Step 3a review-request rules are read as a unit.

| Phase | Body | Gate |
|---|---|---|
| 0, 0.5 | [`phase-0-readiness.md`](references/phase-0-readiness.md) | none |
| 1 | [`phase-1-ci.md`](references/phase-1-ci.md) | If `ci_check_status` returns `infra_unavailable` repeatedly: **REQUIRED: Call `AskUserQuestion`** (keep waiting / escalate) |
| 2 | [`phase-2-comments.md`](references/phase-2-comments.md) | none of its own — `Skill(dev10x:gh-pr-respond)` fires its own gates |
| 2.5 | [`phase-2-comments.md`](references/phase-2-comments.md) | **REQUIRED: Call `AskUserQuestion`** — always fires, through `Skill(dev10x:qa-scope)` |
| 2.7 | [`phase-2-comments.md`](references/phase-2-comments.md) | `resolve_gate(gate="external_notify")`; on `ask`, **REQUIRED: Call `AskUserQuestion`** (post re-review notification / skip) |
| 3, 3.5, 3.6 | [`phase-3-notification.md`](references/phase-3-notification.md) | `resolve_gate(gate="external_notify")`; on `ask`, **REQUIRED: Call `AskUserQuestion`** (post notification / skip notification) |
| 4 | [`phase-4-verification.md`](references/phase-4-verification.md) | none |

In an unattended run (`--unattended`, or `run_mode.mode:
unattended` on the same `resolve_gate` payload, GH-1921) an
`external_notify` gate that resolves to `ask` is treated as `skip`
and fires no widget — see Phase 3 Step 2 and Step 3a.

---

## Micro-Agent Status Protocol

The two micro-agents (`haiku-ci-poll`, `haiku-thread-scan`) end
their output with a single-line JSON payload. The supervisor
parses this payload as the last non-empty line. There is no
`DONE` / `BLOCKED:` text protocol in this architecture — the
JSON IS the contract.

If a micro-agent returns:

- **No JSON on the last line** → treat as a protocol violation;
  surface to the user with the agent's stdout for diagnosis,
  do not retry blindly.
- **`{"verdict": "timeout", ...}`** (ci-poll only) → re-dispatch
  once. If it times out twice, surface to the user — the CI is
  unusually slow or stuck.
- **Empty arrays** (thread-scan) → no unaddressed surfaces,
  proceed to next phase.

There is no main-session fallback path because the supervisor
session already IS the main session. Permission failures cannot
occur silently because the supervisor sees every tool denial
directly.

---

## Important Rules

- **Monitoring scope**: CI checks and review comments through
  review request (Phase 3), then acceptance verification
  (Phase 4). Does NOT cover merge.
- **Do NOT merge PRs.** Merging is the supervisor's manual
  responsibility (or a separate `dev10x:gh-pr-merge` invocation).
- **Phase gates**: 2.5 (QA) always fires `AskUserQuestion`. 2.7
  (re-review) and 3 (notification) each call
  `resolve_gate(gate="external_notify")` and branch on `ask` /
  `auto-advance` / `skip` per session policy — see Phase 2.7 and
  Phase 3 above for the branch pattern.
- **One fixup per comment**: Enforced by `gh-pr-respond`.
- **Poll interval**: `haiku-ci-poll` sleeps 30s per iteration
  internally.
- **Max CI retries**: After 5 consecutive CI failures on the same
  signature, stop and ask the user. The supervisor tracks the
  retry count in its task list, not in the micro-agent.
- **No regular force push**: Use
  `mcp__plugin_dev10x_cli__push_safe`. Exception: post-rebase
  force-with-lease goes through `Skill(dev10x:git-groom)`.
- **Working directory**: Resolve branch via `gh pr view --json
  headRefName` — never hardcode a worktree path.
- **Micro-agent contract (GH-68)**: `haiku-ci-poll` and
  `haiku-thread-scan` are read-only by construction. They cannot
  Edit, Write, `gh pr ready`, push, or invoke further `Skill()`
  calls. The supervisor owns every state change.

---

## Integration with Other Skills

1. **dev10x:gh-pr-create** — Use before this skill to create the draft PR
2. **dev10x:ticket-jtbd** — Delegated by the supervisor in Phase 0
3. **dev10x:gh-pr-respond** — Delegated by the supervisor for review comments (Phase 2)
4. **dev10x:qa-scope** — Delegated by the supervisor in Phase 2.5
5. **dev10x:request-review** — Delegated by the supervisor in Phase 3
6. **dev10x:slack-review-request** — Delegated by the supervisor in Phase 2.7
7. **dev10x:verify-acc-dod** — Delegated by the supervisor in Phase 4
8. **pr-notify.py** — Phase 3 helper (checklist update only)

## Delegation Pattern

```
/dev10x:gh-pr-monitor (supervisor session)
    │
    ├── Step 0: Load BLOCKED OPERATIONS + memory guardrails
    │
    ├── Phase 0: JTBD Job Story check
    │       └── Skill(dev10x:ticket-jtbd) if missing
    │
    ├── Phase 0.5: Review-readiness precondition
    │       └── pr_get → isDraft; pr_ready if still draft
    │
    ├── Phase 1: CI monitoring
    │       └── Agent(haiku-ci-poll) — background, returns verdict JSON
    │       (on failing → supervisor handles in-band, may delegate
    │        to Skill(dev10x:git-commit) / Skill(dev10x:git-groom))
    │
    ├── Phase 2: Comment monitoring
    │       ├── Agent(haiku-thread-scan) — inline, returns surfaces JSON
    │       └── Skill(dev10x:gh-pr-respond) batch mode if surfaces non-empty
    │
    ├── Phase 2.5: QA scope
    │       └── Skill(dev10x:qa-scope)
    │
    ├── Phase 2.7: Re-review notification
    │       ├── resolve_gate(gate="external_notify")
    │       └── Skill(dev10x:slack-review-request)
    │
    ├── Phase 3: Notification
    │       ├── resolve_gate(gate="external_notify")
    │       ├── Skill(dev10x:request-review)
    │       └── pr-notify.py send (checklist-only)
    │
    └── Phase 4: Acceptance criteria
            └── Skill(dev10x:verify-acc-dod)
```
