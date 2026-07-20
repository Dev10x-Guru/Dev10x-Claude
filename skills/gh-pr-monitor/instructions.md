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
- After creating a draft PR with `/Dev10x:gh-pr-create`
- When you want to automate the PR review cycle without blocking your session

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**Auto-advance:** Complete each phase, immediately start the next — no checkpoints under adaptive friction.
Never pause to ask "should I continue?" between phases.

**REQUIRED: Create tasks at session start.** The supervisor
creates these `TaskCreate` calls before dispatching any micro-agent:

1. `TaskCreate(subject="Detect PR context and launch agent", activeForm="Detecting PR context")`
2. `TaskCreate(subject="Check JTBD Job Story (Phase 0)", activeForm="Checking Job Story")`
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
User invokes /Dev10x:gh-pr-monitor
    │
    └── Supervisor session IS the orchestrator (GH-68)
            │
            ├── Phase 0: JTBD Job Story check (supervisor)
            │       └── Skill(Dev10x:ticket-jtbd) if missing
            │
            ├── Phase 1: CI monitoring
            │       ├── dispatch micro-agent: haiku-ci-poll
            │       │     (loops ci-check-status until verdict ≠ pending)
            │       └── supervisor interprets verdict → next action
            │
            ├── Phase 2: Comment monitoring
            │       ├── dispatch micro-agent: haiku-thread-scan
            │       │     (read-only enumerate unresolved threads + findings)
            │       └── supervisor invokes Skill(Dev10x:gh-pr-respond)
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

When the user invokes `/Dev10x:gh-pr-monitor`:

### Step 1: Detect PR context

**Primary (MCP tool):** Call `mcp__plugin_Dev10x_cli__pr_detect`
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

Two narrow haiku sub-agents replace the prior monolithic background
agent. Each has a minimal tool allowlist, a hard turn budget, no
ability to delegate further, and no ability to mutate state.

**Friction-avoidance preamble (REQUIRED, GH-610):** Both micro-agents
run in fresh subagents that never saw the SessionStart friction
briefing. Before each dispatch, fetch the preamble via
`mcp__plugin_Dev10x_cli__background_preamble` and prepend its
`preamble` text to the micro-agent prompt below. The narrow
`allowed_tools` lists are the pre-seeded tool surface — keep them
explicit (do NOT widen to escape a hook block, and never recommend
auto-mode). See `references/orchestration/background-preamble.md`.

#### Micro-agent A: haiku-ci-poll

Polls CI until the verdict changes from `pending`, then returns
the verdict JSON. No decision-making.

```
subagent_type: "general-purpose"
model: "haiku"
run_in_background: true        # supervisor keeps working
max_turns: 50                  # not 200 — bounded work
description: "Poll CI for PR #{pr_number}"
allowed_tools:
  - mcp__plugin_Dev10x_cli__ci_check_status
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-monitor/scripts/ci-check-status.py:*)
  - Bash(sleep:*)
  - SendMessage                # deliver the verdict (GH-776)
disallowed_tools:
  - Edit, Write, NotebookEdit
  - Bash(git:*), Bash(gh pr ready:*), Bash(gh pr edit:*),
    Bash(gh pr merge:*)
  - Skill(*)                   # cannot delegate further
  - mcp__plugin_Dev10x_cli__push_safe
  - mcp__plugin_Dev10x_cli__update_pr
prompt: |
  You are a CI-polling micro-agent. Your ONLY job is to loop
  ci-check-status.py until verdict changes from "pending", then
  output the final JSON verdict and exit.

  Loop:
    1. Run: ci-check-status.py --pr {pr_number} --repo {repo}
    2. Parse the JSON. If verdict == "pending" or "empty", sleep 30s.
       (A single `ci_check_status(wait=true)` call self-polls with a
       budget kept under the ~1800s MCP idle-timeout, GH-808 F2 — it
       returns `infra_unavailable` rather than hanging if checks never
       register.)
    3. If verdict in ["green", "failing", "conflicting",
       "infra_unavailable"], deliver
       the verdict JSON and exit. Because you run in the background,
       plain stdout is NOT read — you MUST call
       SendMessage(to="main", summary="ci <verdict>",
       message=<the verdict JSON>) to deliver it. The JSON must be
       the LAST line of the SendMessage payload (GH-776).

  You MUST NOT:
    - Decide what to do about the verdict — that is the supervisor's
      job.
    - Mark the PR ready, edit anything, comment, or push.
    - Invoke any Skill or further Agent.
    - Continue looping past 50 turns. If you reach turn 45 with the
      verdict still pending, SendMessage
      {"verdict": "timeout", "polled_turns": <N>} to main and exit.

  Deliver the verdict JSON via SendMessage(to="main", …) — it must be
  the LAST line of that payload. Do NOT rely on bare stdout; a
  background agent's stdout never reaches the supervisor (GH-776).
```

#### Micro-agent B: haiku-thread-scan

Read-only enumerates unresolved review threads, body findings,
and top-level automated comments. Returns structured JSON. No
decision-making, no replies, no state changes.

```
subagent_type: "general-purpose"
model: "haiku"
run_in_background: false       # cheap, run inline
max_turns: 20
description: "Scan PR #{pr_number} threads"
allowed_tools:
  - Bash(gh api graphql:*)
  - Bash(gh api repos/:*)
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-merge/scripts/check-top-level-comments.sh:*)
  - mcp__plugin_Dev10x_cli__check_top_level_comments
disallowed_tools:
  - Edit, Write, NotebookEdit
  - Bash(git:*), Bash(gh pr ready:*), Bash(gh pr edit:*),
    Bash(gh api -X POST:*), Bash(gh api -X PATCH:*),
    Bash(gh api -X DELETE:*)
  - Skill(*)
  - mcp__plugin_Dev10x_cli__push_safe
  - mcp__plugin_Dev10x_cli__update_pr
prompt: |
  You are a PR-thread-scanning micro-agent. Your ONLY job is to
  enumerate unaddressed review surfaces on PR #{pr_number} and
  return structured JSON. You do not reply, edit, or change state.

  Steps:
    1. GraphQL query reviewThreads where isResolved == false.
       Capture: thread id, first comment author, body, file:line.
    2. Fetch reviews via REST; for each review with a non-empty
       body, detect structured findings (CRITICAL:, BLOCKING:,
       INFO:, **[BLOCKING]**, numbered items with file:line).
       Mark as unaddressed if no top-level PR comment replies
       with `Re:` matching the finding ID.
    3. Call mcp__plugin_Dev10x_cli__check_top_level_comments(
       repo="{repo}", pr_number={pr_number}) — do NOT eyeball
       severity yourself. It spans BOTH issue comments AND submitted
       review bodies (flagging bots by account type, known login, or
       HTML marker, GH-743 F2) and returns two structured buckets
       (GH-808 F1): `blocking` (REQUIRED/CRITICAL/BLOCKING) and
       `needs_disposition` (non-blocking INFO/NOTE/SUGGESTION,
       including review-body findings a severity-only scan missed).
       Put `blocking` findings in `top_level_findings` and
       `needs_disposition` findings in `needs_disposition` below. A
       "clean" scan requires BOTH buckets empty — a non-blocking INFO
       still needs an explicit disposition (a `Re:` reply satisfies it).

  Output as the LAST line, single-line JSON:
    {
      "unresolved_threads": [{"id": ..., "author": ..., "path": ..., "body": ...}],
      "body_findings": [{"review_id": ..., "summary": ...}],
      "top_level_findings": [{"comment_id": ..., "summary": ...}],
      "needs_disposition": [{"comment_id": ..., "summary": ...}]
    }

  You MUST NOT:
    - Reply to any thread, even with "acknowledged".
    - Resolve any thread.
    - Edit the PR body or any comment.
    - Invoke any Skill, gh pr ready, or gh api with -X POST/PATCH/DELETE.
    - Speculate on which threads are "actionable" vs not — return
      all unresolved, the supervisor classifies.
```

**Why split into two micro-agents?** CI polling is long-running
and runs in the background while the supervisor works on other
things. Thread scanning is cheap and runs inline so the supervisor
has the result immediately. Combining them would force the cheap
scan to wait for the slow poll.

**Why haiku for both?** Polling and structured enumeration are
mechanical work — no reasoning needed. Haiku is cheap and its
narrow tool list prevents it from doing anything else.

**Anti-pattern (GH-68 incident #2):** Combining the orchestrator
and the poller into one big haiku with `max_turns: 200` and
`mode: dontAsk` is exactly what caused the issue. Do NOT do that.
Each micro-agent has a single observable job and a single-line
JSON output contract.

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
args passed to `/Dev10x:gh-pr-monitor` (case-insensitive) for:

- `do NOT ...` / `do not ...` (capture trailing clause up to
  newline or `.`)
- `INTENTIONALLY ...`
- `leave UNSQUASHED` / `leave unsquashed`
- `do NOT auto-groom` / `no auto-groom`
- `keep ... open` / `do not resolve`
- Any line beginning with `MUST NOT` or `NEVER`

Restate each matched directive verbatim at the start of the
supervisor's monitoring plan ("Per the dispatch prompt: …"). Before
invoking `Skill(Dev10x:git-groom)`, `Skill(Dev10x:gh-pr-respond)`,
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

## Phase 0: JTBD Job Story Check

The PR body **must** start with a JTBD Job Story as its first paragraph.

1. Fetch the current PR body:
   ```bash
   gh pr view {pr_number} --json body -q '.body'
   ```

2. Check if the first paragraph matches the Job Story pattern:
   - Starts with `**When**` (bold "When")
   - Contains `**[actor] wants to**` and `**so [beneficiary] can**`
     (legacy first-person `**I want to**` / `**so I can**` also matches)
   - Uses the project or ticket language; when BDD/Gherkin-derived
     keywords appear, they match Cucumber's language reference:
     https://cucumber.io/docs/gherkin/languages/

3. If a valid Job Story is present → skip to Phase 1.

4. If missing or malformed → generate one using the `Dev10x:ticket-jtbd` skill.

5. After the skill completes, verify the PR body now starts with the
   Job Story.

---

## Phase 1: CI Monitoring (server-side wait, preferred)

The supervisor does not loop on CI itself.

### Primary mechanism: `ci_check_status(wait=true)` (GH-675)

**Preferred — call `mcp__plugin_Dev10x_cli__ci_check_status`
directly with `wait=true`.** It polls **server-side** to a
terminal verdict (`green` / `failing` / `conflicting`) with no
Bash, no `sleep`, and no background sub-agent:

```
mcp__plugin_Dev10x_cli__ci_check_status(
    pr_number={pr_number}, repo="{repo}", wait=True)
```

This returns the same verdict JSON the `haiku-ci-poll` micro-agent
emits, so the **Interpret verdict** table below applies unchanged.

**Why this is preferred over the haiku-ci-poll micro-agent:** the
micro-agent's `sleep 30` loop hits a permission boundary in some
environments and returns after a **single** poll with a
non-terminal verdict, reporting "I can execute immediate Bash
commands but not long-running background polling loops" (GH-675).
The orchestrator then never receives a terminal verdict. Polling
server-side via `ci_check_status(wait=true)` removes the `sleep`
loop, the Bash dependency, and the `gh-pr-checks-watch` friction
class entirely.

### Fallback: dispatch the `haiku-ci-poll` micro-agent

Use the micro-agent (see "Micro-agent A" above) only when
`ci_check_status(wait=true)` is unavailable (older plugin version)
or you specifically want the poll to run in the background while
the supervisor works on Phase 2. It loops `ci-check-status.py`
until the verdict changes from `"pending"` and returns the final
JSON.

```
Agent(
    subagent_type="general-purpose",
    model="haiku",
    run_in_background=True,
    max_turns=50,
    description="Poll CI for PR #{pr_number}",
    allowed_tools=[<see Micro-agent A spec>],
    disallowed_tools=[<see Micro-agent A spec>],
    prompt=<see Micro-agent A prompt, with {pr_number}, {repo} filled in>
)
```

Because `run_in_background=True`, the supervisor receives a
completion notification when the poll ends — but that notification
carries NO content, so the micro-agent must deliver the verdict JSON
via `SendMessage(to="main", …)` (GH-776); bare stdout is never read.
A completion notification with no `SendMessage` means the poll
finished WITHOUT delivering — nudge it once, then fall back to
`ci_check_status(wait=true)`. The supervisor can work on Phase 2
(thread scan) or other unrelated tasks in the meantime. If the
micro-agent returns after a single poll with a non-terminal verdict
(the GH-675 sleep-permission limitation), fall back to
`ci_check_status(wait=true)`.

### Interpret verdict

When the micro-agent returns, parse the JSON. The `verdict` field
drives the next action:

| `verdict`       | Supervisor action |
|-----------------|-------------------|
| `green`         | Run Post-CI comment re-check (below), then Phase 2 |
| `failing`       | Read `checks` array, branch on failure type (see CI Failure Handling) |
| `conflicting`   | Rebase onto base branch (see Conflict Handling) |
| `empty`         | Re-dispatch ci-poll after 60s — GitHub hasn't registered checks yet |
| `timeout`       | Micro-agent hit the 50-turn cap. Re-dispatch with note "session #2"; if it times out twice, surface to user |

**Pending verdict is impossible** at this layer — the micro-agent's
contract is "loop until verdict ≠ pending". If the supervisor ever
sees `"pending"` in the returned JSON, something is wrong with the
micro-agent prompt; treat as `BLOCKED: ci-poll-protocol-violation`
and stop.

**Draft-to-ready SKIPPED guard (GH-774):** The script returns
`"empty"` when all checks are SKIPPED (non_skipping == 0). The
supervisor must re-dispatch after 60s rather than treating this
as green — GitHub re-registers checks after `gh pr ready`. The
micro-agent already returns `"empty"` not `"green"` in this case.

**Why not loop in the supervisor's session?** Because each loop
iteration costs a supervisor turn, and supervisor turns are
expensive context. Pushing the loop into a haiku sub-process
saves cost AND removes any chance of the loop "deciding" to do
something else mid-wait.

### CI Failure Handling

The supervisor handles CI failures directly — it has full
reasoning context, sees the BLOCKED OPERATIONS list and memory
guardrails loaded in Step 0, and can ask the user before any
ambiguous change. There is no `BLOCKED:` status line in this
architecture; the supervisor is the parent, and it decides
in-band.

Anti-pattern (the incident in GH-68 incident #2): a background
haiku agent received `verdict: failing`, ran `Edit` to "fix" a
test it had no business changing, created a fixup that
re-introduced reviewer-rejected code, then auto-grooved the
regression. The new architecture removes this failure surface
because the supervisor's reasoning capacity is in the loop.

| Failure Type | Supervisor action |
|---|---|
| ruff/black/isort | Run the formatter; commit via `Skill(Dev10x:git-commit)` |
| mypy / flake8 / import errors | Apply fix; commit via `Skill(Dev10x:git-commit)` |
| pytest failures | Read the test + code; decide between fix and ticket; act |
| Coverage < 100% | Add tests for uncovered lines |
| gitlint (title > 72 chars) | Reword via `git commit --amend` or `Skill(Dev10x:git-groom)` |
| git-history-linting (fixup! only) | Delegate to `Skill(Dev10x:git-groom)` — groom enforces its own preconditions, including the thread-open refusal (GH-68, Fix E) |

**Before any commit/groom**, the supervisor MUST:

1. Re-read the BLOCKED OPERATIONS extracted in Step 0. If the
   intended action matches any directive (e.g., `leave UNSQUASHED`
   vs. an autosquash plan), stop and ask the user.
2. Apply the self-introduced regression guard (GH-68, Fix C):
   read `git reflog`, identify commits authored within this
   monitoring session. If HEAD is one of them AND the failing
   test was passing on `HEAD~1`, recover with `git reset --hard
   HEAD~1` or `git revert HEAD` instead of a counter-fixup. This
   guard exists because the supervisor itself might have just
   pushed the regression a few turns ago.
3. Re-dispatch `haiku-ci-poll` after the fix lands; wait 60s
   first so GitHub registers new check suites.

### Conflict Handling

When `gh pr view` reports `mergeable: CONFLICTING`:

1. Resolve the base branch via `mcp__plugin_Dev10x_cli__pr_detect`
   (returns `baseRefName`).

2. Delegate the rebase + force-push to `Skill(Dev10x:git-groom)` —
   it fetches the base, rebases, and runs the protected-branch
   safety checks before force-pushing. Do NOT call `git rebase` or
   `git push --force-with-lease` directly from this skill: routing
   through the wrapper preserves the autosquash, gitmoji, and
   protected-branch guardrails (see Skill Routing Enforcement in
   `skills/work-on/instructions.md`).

3. If `Dev10x:git-groom` reports unresolved conflicts, stop the
   monitor and report the conflicting files to the user.

4. After the wrapper completes the force-push, wait 30 seconds for
   GitHub to re-compute mergeability and re-run CI, then restart the
   Phase 1 loop.

### Post-CI Comment Re-check (REQUIRED)

**Hard rule (GH-465):** After CI returns `green`, the supervisor
re-scans for review comments before marking the PR ready. CI
hygiene reviews post comments during the CI run, so the initial
comment scan at session start can miss them.

Dispatch `haiku-thread-scan` (Micro-agent B). It returns:

```json
{
  "unresolved_threads": [...],
  "body_findings": [...],
  "top_level_findings": [...],
  "needs_disposition": [...]
}
```

Sum ALL FOUR arrays (incl. `needs_disposition`, GH-808 F1). If any
are non-empty → enter Phase 2. If all four are empty → mark the PR
ready (`gh pr ready {pr_number}`) and proceed to Phase 2.5. A
non-blocking INFO in `needs_disposition` counts — it must be
addressed or explicitly deferred before the PR reads clean.

---

## Phase 2: Review Comment Handling (orchestrator + thread-scan)

The supervisor handles comment response in-band, with full
reasoning context and the user available for `AskUserQuestion`
gates. Loop until no unaddressed comments remain.

1. Dispatch `haiku-thread-scan` (Micro-agent B) inline (not
   background — it's cheap and the supervisor needs the result
   before the next decision).

2. Parse the returned JSON. If all three arrays are empty, exit
   Phase 2 and proceed to Phase 2.5.

3. Invoke `Skill(Dev10x:gh-pr-respond)` in batch mode with the PR
   URL — that skill runs in the supervisor session, has full
   reasoning + user gates, and handles validation, fixup commits,
   and reply posting:

   ```
   Skill("Dev10x:gh-pr-respond", "{pr_url}")
   ```

   The supervisor's BLOCKED OPERATIONS list (Step 0) is preserved
   across this delegation — `gh-pr-respond` does not see it
   automatically, so if a thread asks for an operation that
   matches a directive (e.g., reviewer requests "squash these
   fixups now" when the dispatch prompt said `leave UNSQUASHED`),
   the supervisor refuses the action and explains to the reviewer
   via a reply.

4. After `gh-pr-respond` completes, fixups have been pushed; CI
   will re-run. Re-dispatch `haiku-ci-poll` (Phase 1) until
   verdict is green again, then re-dispatch `haiku-thread-scan`
   in case more comments arrived during the cycle.

5. When `haiku-thread-scan` returns three empty arrays AND
   `haiku-ci-poll` returns `green` AND at least one approval
   exists (or no reviews yet) → Phase 2 complete.

### Counting Unaddressed Comments (Thread Resolution Awareness)

**CRITICAL (GH-464):** Do NOT count root PR comments as unaddressed
based solely on the REST API (`gh api .../pulls/.../comments`). The
REST API returns ALL root comments regardless of thread resolution
status. Use the GraphQL `reviewThreads` query to check `isResolved`:

```bash
gh api graphql -f query='
query($owner: String!, $repo: String!, $pr: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $pr) {
      reviewThreads(first: 100) {
        nodes {
          isResolved
          comments(first: 1) {
            nodes { databaseId path body author { login } }
          }
        }
      }
    }
  }
}' -f owner='{owner}' -f repo='{repo}' -F pr={pr_number} \
  --jq '[.data.repository.pullRequest.reviewThreads.nodes[]
        | select(.isResolved == false)
        | .comments.nodes[0]]'
```

Only threads where `isResolved == false` AND the author has not
replied count as unaddressed. Resolved threads are done — do not
report them as needing attention.

### Exit condition for Phase 2 loop

Move to Phase 2.5 when ALL of these are true:
- All CI checks passing
- No unresolved review threads (use GraphQL `isResolved` check)
- No unaddressed body-only review findings (GH-564) — check
  review bodies for structured findings without corresponding
  top-level PR comment replies
- No unaddressed top-level automated review comments (GH-698)
  — check `issueComments` for severity markers from bot users
- PR has at least one approval OR no reviews yet

---

## Phase 2.5: QA Scope Assessment (REQUIRES USER CONFIRMATION)

This phase runs ONCE when Phase 2 completes. It delegates to the
`Dev10x:qa-scope` skill if available.

1. Invoke the Dev10x:qa-scope skill:
   ```
   Skill(skill="Dev10x:qa-scope", args="{pr_number}")
   ```

   The Dev10x:qa-scope skill will:
   - Analyze the PR diff for QA risk (low/medium/high)
   - Check the project's e2e test directory for existing coverage
   - Present a QA assessment to the user via AskUserQuestion

2. Wait for the skill to complete before proceeding to Phase 3.

3. If Dev10x:qa-scope determines the change is low-risk (config-only,
   test-only, docs-only), it will skip ticket creation automatically.

**Note:** This phase only runs once per PR monitor session. If already
executed, skip directly to Phase 3.

---

## Phase 2.7: Re-review Notification (REQUIRES USER CONFIRMATION)

This phase runs when Phase 2 addressed review comments (i.e., at least
one reviewer requested changes and those changes have been pushed). Skip
if Phase 2 found no comments to address.

**Trigger:** PR had CHANGES_REQUESTED reviews AND fixup commits were
created to address them.

### Step 1: Identify reviewers who requested changes

```bash
gh pr view {pr_number} --json reviews \
  --jq '.reviews[] | select(.state=="CHANGES_REQUESTED") | .author.login'
```

### Step 2: Compose and format each notification

For each reviewer who requested changes, compose:
```
@{reviewer} please take another look
```

Format this as a Slack message suitable for posting.

### Step 3: Resolve notification gate

Call `mcp__plugin_Dev10x_cli__resolve_gate(gate="external_notify",
context={})` before posting.

1. `effect == "ask"` → Fire the EXISTING `AskUserQuestion` widget
   showing the exact message that will be posted. Options: "Post
   re-review notification" / "Skip".
2. `effect == "auto-advance"` → Proceed straight to Step 4 (post
   the notification) without prompting. Surface the returned
   `record` line in the transcript.
3. `effect == "skip"` → Do not post. Skip straight to Phase 3.
4. Response has an `error` key → fail safe: treat as `ask`.

### Step 4: Post the notification

If the gate resolved to post (user approved the `ask` widget, or
the gate auto-advanced), invoke the skill with the composed
message. The skill reads the project's Slack config and posts to
the configured channel.

Example invocation:
```
Skill(skill="Dev10x:slack-review-request", args="--pr {pr_number} --repo {repo} --message '@{reviewer} please take another look'")
```

The Dev10x:slack-review-request skill will:
- Resolve the project's configured channel from userspace config
- Post the message to that channel
- Report the result back to the agent

---

## Phase 3: Notification (REQUIRES USER CONFIRMATION)

**CRITICAL: Do NOT post notifications without resolving the gate
first.**

Phase 3's notification step calls `resolve_gate(gate=
"external_notify")` (Step 2 below) and branches on the returned
`effect`. The resolver — not this skill — decides whether to
ask, auto-advance, or skip, based on session policy (preset,
overlays, including the solo-maintainer overlay). Do NOT
special-case `friction_level` or `active_modes` in prose here.

### Step 0: Verify PR state via MCP

**Hard rule: Verify final PR state with the MCP tool — NEVER use
raw `gh pr view` or `gh pr checks`.**

`mcp__plugin_Dev10x_cli__verify_pr_state(pr_number={pr_number})`

Parse `is_draft`, `state`, `review_decision`, and `checks_passing`
from the response. Only proceed to notification if checks pass and
no blocking issues.

### Step 1: Prepare

Gather PR info, count open threads, verify readiness:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-monitor/scripts/pr-notify.py \
  prepare --pr {pr_number} --repo {repo}
```

If `open_threads > 0`, verify the count using GraphQL `isResolved`
(see "Counting Unaddressed Comments" in Phase 2). Only return to
Phase 2 if unresolved threads actually exist — `pr-notify.py` may
count resolved threads as open if it uses the REST API.

*Why?* Reviewers should only be pinged when the PR is fully ready.

### Step 2: Resolve notification gate

Call `mcp__plugin_Dev10x_cli__resolve_gate(gate="external_notify",
context={})`.

1. `effect == "ask"` → Fire the EXISTING `AskUserQuestion` widget:
   - Question: "PR #{pr_number} is ready for review. Post notification?"
   - Show the formatted message from the prepare output
   - Options: "Post notification" / "Skip notification"
2. `effect == "auto-advance"` → Proceed directly to Step 3
   (post the notification) without prompting. Surface the
   returned `record` line in the transcript.
3. `effect == "skip"` → Skip notification entirely — go
   directly to Step 4 (checklist-only, no Slack, no reviewer
   assignment).
4. Response has an `error` key → fail safe: treat as `ask`.

### Step 3: Execute (if user approves)

If user approves, execute two delegated steps in sequence:

**Step 3a: Request review (GitHub + Slack)**

```
Skill(skill="Dev10x:request-review", args="--pr {pr_number} --repo {repo}")
```

The Dev10x:request-review skill will:
- Assign GitHub reviewers from project config
- Post Slack review notification from project config
- Each step may skip independently based on per-project config

**Step 3b: Update PR checklist**

```bash
${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-monitor/scripts/pr-notify.py \
  send --pr {pr_number} --repo {repo} \
  --skip-slack --skip-reviewers
```

This call runs checklist-only mode — no Slack posting, no reviewer
assignment (those were handled by the delegated skill above).

### Step 4: Execute (if user declines)

If user declines the notification, run checklist-only:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-monitor/scripts/pr-notify.py \
  send --pr {pr_number} --repo {repo} \
  --skip-slack --skip-reviewers
```

### Step 5: Report final status

Run the status report command and include its output in the final report:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-monitor/scripts/pr-notify.py \
  status --pr {pr_number} --repo {repo}
```

This outputs a markdown report with three sections:
- **CI Check Status** — table with check name, pass/fail, duration
- **Review Comments** — count and list of unhandled comments
- **Reviewers** — table with reviewer names and review status

Include the full output in the agent's final report to the supervisor.

---

## Phase 3.5: Post-Merge Milestone Cleanup (GH-187)

If the PR has merged (state observed by `haiku-ci-poll` as
`MERGED`, or `gh pr view --json state,milestone` shows
`state: MERGED`) and the PR was assigned to a milestone,
check whether the milestone can now be closed.

1. Read `milestone.number` and `milestone.open_issues` from
   `gh pr view --json milestone`.
2. If `open_issues == 0`, call the MCP tool:
   ```
   mcp__plugin_Dev10x_cli__milestone_close(number=<N>)
   ```
   This wraps `gh api -X PATCH repos/{repo}/milestones/{N} -f
   state=closed` — which the plugin's permission manifest blocks
   at the Bash layer. The MCP tool has the permission baked in.
3. If `open_issues > 0`, skip the close — the milestone still
   has work. Report `Milestone #{N}: {open_issues} open issues
   remaining` in the final status.

Skip this phase if `milestone == null`. Never invoke
`milestone_close` via raw `gh api` — the permission gap is
intentional outside the MCP tool.

## Phase 4: Acceptance Criteria Verification

After Phase 3 completes, verify acceptance criteria before the
agent's final status report. This catches uncommitted files,
failing checks, or incomplete work that earlier phases missed.

1. Invoke the verification skill:
   ```
   Skill(skill="Dev10x:verify-acc-dod")
   ```

   The skill auto-detects the work type from session context and
   adapts to the current friction level. At `adaptive` level it
   runs fully unattended — auto-passing or auto-failing without
   blocking the agent.

2. If all checks pass → include "Acceptance criteria: PASSED" in
   the final status report.

3. If any check fails → include "Acceptance criteria: FAILED" with
   the failing checks in the final status report. Do NOT re-enter
   earlier phases — report the failures and let the supervisor
   decide next steps.

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
  responsibility (or a separate `Dev10x:gh-pr-merge` invocation).
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
  `mcp__plugin_Dev10x_cli__push_safe`. Exception: post-rebase
  force-with-lease goes through `Skill(Dev10x:git-groom)`.
- **Working directory**: Resolve branch via `gh pr view --json
  headRefName` — never hardcode a worktree path.
- **Micro-agent contract (GH-68)**: `haiku-ci-poll` and
  `haiku-thread-scan` are read-only by construction. They cannot
  Edit, Write, `gh pr ready`, push, or invoke further `Skill()`
  calls. The supervisor owns every state change.

---

## Integration with Other Skills

1. **Dev10x:gh-pr-create** — Use before this skill to create the draft PR
2. **Dev10x:ticket-jtbd** — Delegated by the supervisor in Phase 0
3. **Dev10x:gh-pr-respond** — Delegated by the supervisor for review comments (Phase 2)
4. **Dev10x:qa-scope** — Delegated by the supervisor in Phase 2.5
5. **Dev10x:request-review** — Delegated by the supervisor in Phase 3
6. **Dev10x:slack-review-request** — Delegated by the supervisor in Phase 2.7
7. **Dev10x:verify-acc-dod** — Delegated by the supervisor in Phase 4
8. **pr-notify.py** — Phase 3 helper (checklist update only)

## Delegation Pattern

```
/Dev10x:gh-pr-monitor (supervisor session)
    │
    ├── Step 0: Load BLOCKED OPERATIONS + memory guardrails
    │
    ├── Phase 0: JTBD Job Story check
    │       └── Skill(Dev10x:ticket-jtbd) if missing
    │
    ├── Phase 1: CI monitoring
    │       └── Agent(haiku-ci-poll) — background, returns verdict JSON
    │       (on failing → supervisor handles in-band, may delegate
    │        to Skill(Dev10x:git-commit) / Skill(Dev10x:git-groom))
    │
    ├── Phase 2: Comment monitoring
    │       ├── Agent(haiku-thread-scan) — inline, returns surfaces JSON
    │       └── Skill(Dev10x:gh-pr-respond) batch mode if surfaces non-empty
    │
    ├── Phase 2.5: QA scope
    │       └── Skill(Dev10x:qa-scope)
    │
    ├── Phase 2.7: Re-review notification
    │       ├── resolve_gate(gate="external_notify")
    │       └── Skill(Dev10x:slack-review-request)
    │
    ├── Phase 3: Notification
    │       ├── resolve_gate(gate="external_notify")
    │       ├── Skill(Dev10x:request-review)
    │       └── pr-notify.py send (checklist-only)
    │
    └── Phase 4: Acceptance criteria
            └── Skill(Dev10x:verify-acc-dod)
```
